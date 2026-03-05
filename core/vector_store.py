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

    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir
        self.project_names: List[str] = []
        self.fingerprints: Dict[str, dict] = {}  # name -> {dim_id: [float, ...]}

    def add_project(self, name: str, fingerprint) -> None:
        """添加项目到内存索引。fingerprint 需有 .embeddings 属性。"""
        if name in self.fingerprints:
            logger.info(f"项目 {name} 已存在，更新指纹")
            self.project_names.remove(name)
            del self.fingerprints[name]

        self.project_names.append(name)
        self.fingerprints[name] = fingerprint.embeddings

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
        多维度加权余弦相似度检索。

        Args:
            query_fingerprint: 查询项目的 Fingerprint 对象
            top_k:             返回 Top-K 个最相似项目
            exclude_self:      是否排除与查询同名的项目

        Returns:
            [{ "name": str, "total_score": float, "dim_scores": {dim_id: float} }, ...]
        """
        if not self.project_names:
            return []

        from core.vectorizer import DIMENSION_MAP, get_dimension_weights

        weights = get_dimension_weights()
        dim_ids = sorted(DIMENSION_MAP.keys())

        # ── 方案 1：逐维度加权余弦（精确，项目数少时性能足够） ──
        results = []
        for name in self.project_names:
            if exclude_self and name == query_fingerprint.name:
                continue

            target_emb = self.fingerprints[name]
            total_score = 0.0
            dim_scores = {}

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

                # 余弦相似度
                norm_q = np.linalg.norm(q_vec)
                norm_t = np.linalg.norm(t_vec)
                if norm_q < 1e-8 or norm_t < 1e-8:
                    cos_sim = 0.0
                else:
                    cos_sim = float(np.dot(q_vec, t_vec) / (norm_q * norm_t))

                dim_scores[dim_id] = round(cos_sim, 4)
                total_score += weights.get(dim_id, 0.0) * cos_sim

            results.append({
                "name": name,
                "total_score": round(total_score, 4),
                "dim_scores": dim_scores,
            })

        # 按总分降序
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
