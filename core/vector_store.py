"""OS-Agent C: 本地向量存储与检索模块

基于 numpy 的轻量级内存向量索引，支持多维度加权余弦相似度检索。
每个项目的向量持久化在 output/<repo>/fingerprint.json 中。
"""
import os
import json
import logging
from typing import Dict, List, Optional

import numpy as np

logger = logging.getLogger("vector_store")

class VectorStore:
    """基于 numpy 的内存向量存储与加权余弦相似度检索。"""

    # 框架共享维度（框架本身决定的特征，不代表自研代码相似）
    FRAMEWORK_SHARED_DIMS = {"D1_tech_stack", "D2_boot_arch", "D7_device_driver"}
    # 自研核心维度（真正区分两个项目自研代码相似度的维度）
    CUSTOM_CORE_DIMS = {"D3_memory", "D4_process_sched", "D5_trap_syscall",
                        "D6_filesystem", "D8_sync_ipc"}

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir
        self.project_names: List[str] = []
        self.fingerprints: Dict[str, dict] = {}          # name -> {dim_id: [float, ...]}
        self._struct_features_cache: Dict[str, dict] = {} # name -> struct_features dict

    def add_project(self, name: str, fingerprint) -> None:
        """添加项目到内存索引。fingerprint 需有 .embeddings 和 .struct_features 属性。"""
        if name in self.fingerprints:
            logger.info(f"项目 {name} 已存在，更新指纹")
            self.project_names.remove(name)
            del self.fingerprints[name]
            self._struct_features_cache.pop(name, None)

        self.project_names.append(name)
        self.fingerprints[name] = fingerprint.embeddings
        # 缓存 struct_features（向后兼容旧指纹对象）
        sf = getattr(fingerprint, "struct_features", {}) or {}
        self._struct_features_cache[name] = sf

    # ------------------------------------------------------------------
    # 精确字段加分
    # ------------------------------------------------------------------
    @staticmethod
    def _compute_struct_score(sf_query: dict, sf_target: dict) -> float:
        """
        计算两个 struct_features 之间的精确字段加分（最高 0.15）。
        字段均为 null 时不加分（双方未知不等于相同）。
        """
        score = 0.0

        def _match(key, bonus):
            q = sf_query.get(key)
            t = sf_target.get(key)
            if q is not None and t is not None and q == t:
                return bonus
            return 0.0

        score += _match("allocator_crate", 0.04)
        score += _match("network_stack", 0.03)
        score += _match("fat32_source", 0.02)
        # trapframe_bytes 做 int 规范化，避免 "248" vs 248 的字符串/整数不等问题
        q_tf = sf_query.get("trapframe_bytes")
        t_tf = sf_target.get("trapframe_bytes")
        if q_tf is not None and t_tf is not None:
            try:
                if int(q_tf) == int(t_tf):
                    score += 0.03
            except (TypeError, ValueError):
                pass

        # syscall_count_real：差值越小加分越多（最高 0.03）
        # 做 int() 转换，防止 LLM 将数字以字符串形式输出导致 TypeError
        q_cnt = sf_query.get("syscall_count_real")
        t_cnt = sf_target.get("syscall_count_real")
        if q_cnt is not None and t_cnt is not None:
            try:
                delta = abs(int(q_cnt) - int(t_cnt))
                score += (1.0 - min(delta / 50.0, 1.0)) * 0.03
            except (TypeError, ValueError):
                pass  # 无法转换则不加分

        return min(score, 0.15)

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------
    def search_similar(
        self,
        query_fingerprint,
        top_k: int = 5,
        exclude_self: bool = True,
    ) -> List[Dict]:
        """
        多维度加权余弦相似度检索（含框架感知权重 + 精确字段加分）。

        同框架项目：框架贡献的维度（D1/D2/D7）权重减半，自研核心维度（D3~D8）权重×1.4，
        以放大自研代码差异，避免因共用框架导致虚高的相似分数。

        Args:
            query_fingerprint: 查询项目的 Fingerprint 对象
            top_k:             返回 Top-K 个最相似项目
            exclude_self:      是否排除与查询同名的项目

        Returns:
            [{ "name": str, "total_score": float, "cosine_score": float,
               "struct_score": float, "same_framework": bool,
               "dim_scores": {dim_id: float} }, ...]
        """
        if not self.project_names:
            return []

        from core.vectorizer import DIMENSION_MAP, get_dimension_weights

        base_weights = get_dimension_weights()
        dim_ids = sorted(DIMENSION_MAP.keys())
        q_sf = getattr(query_fingerprint, "struct_features", {}) or {}
        q_framework = q_sf.get("framework", "unknown")

        results = []
        for name in self.project_names:
            if exclude_self and name == query_fingerprint.name:
                continue

            target_emb = self.fingerprints[name]
            t_sf = self._struct_features_cache.get(name, {})
            t_framework = t_sf.get("framework", "unknown")

            # 框架感知：同框架时调整权重
            same_framework = (
                q_framework not in ("unknown", None)
                and q_framework == t_framework
            )
            if same_framework:
                raw_weights = {}
                for d in dim_ids:
                    w = base_weights.get(d, 0.0)
                    if d in VectorStore.FRAMEWORK_SHARED_DIMS:
                        raw_weights[d] = w * 0.5
                    elif d in VectorStore.CUSTOM_CORE_DIMS:
                        raw_weights[d] = w * 1.4
                    else:
                        raw_weights[d] = w
                total_w = sum(raw_weights.values()) or 1.0
                weights = {d: v / total_w for d, v in raw_weights.items()}
            else:
                total_w = sum(base_weights.values()) or 1.0
                weights = {d: v / total_w for d, v in base_weights.items()}

            dim_scores = {}
            cosine_weighted = 0.0

            for dim_id in dim_ids:
                q_vec = np.array(
                    query_fingerprint.embeddings.get(dim_id, []),
                    dtype=np.float32,
                )
                t_vec = np.array(
                    target_emb.get(dim_id, []),
                    dtype=np.float32,
                )
                if q_vec.size == 0 or t_vec.size == 0:
                    dim_scores[dim_id] = 0.0
                    continue

                norm_q = np.linalg.norm(q_vec)
                norm_t = np.linalg.norm(t_vec)
                if norm_q < 1e-8 or norm_t < 1e-8:
                    cos_sim = 0.0
                else:
                    cos_sim = float(np.dot(q_vec, t_vec) / (norm_q * norm_t))

                dim_scores[dim_id] = round(cos_sim, 4)
                cosine_weighted += weights.get(dim_id, 0.0) * cos_sim

            # 精确字段加分
            struct_score = VectorStore._compute_struct_score(q_sf, t_sf)
            total_score = cosine_weighted + struct_score

            results.append({
                "name": name,
                "total_score": round(total_score, 4),
                "cosine_score": round(cosine_weighted, 4),
                "struct_score": round(struct_score, 4),
                "same_framework": same_framework,
                "dim_scores": dim_scores,
            })

        results.sort(key=lambda r: r["total_score"], reverse=True)
        return results[:top_k]

    # ------------------------------------------------------------------
    # 批量构建索引（扫描 output/ 下所有项目）
    # ------------------------------------------------------------------
    def build_index(self) -> int:
        """
        扫描 output/ 下所有 <repo>/fingerprint.json，加载到内存索引。

        Returns:
            加载的项目数量
        """
        from core.vectorizer import Fingerprint

        count = 0
        for entry in sorted(os.listdir(self.output_dir)):
            entry_path = os.path.join(self.output_dir, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry.startswith("_"):  # 跳过 _vector_index 等
                continue

            fp_path = os.path.join(entry_path, "fingerprint.json")
            if not os.path.exists(fp_path):
                continue

            try:
                fp = Fingerprint.load(fp_path)
                self.add_project(fp.name, fp)
                count += 1
                logger.info(f"已加载指纹: {fp.name}")
            except Exception as e:
                logger.warning(f"加载 {fp_path} 失败: {e}")

        return count

    @property
    def size(self) -> int:
        return len(self.project_names)

    def list_projects(self) -> List[str]:
        return list(self.project_names)

    def has_project(self, name: str) -> bool:
        return name in self.fingerprints
