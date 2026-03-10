"""
OS-Agent AST-based Code RAG Engine

利用 tree-sitter 将 C/Rust 源码静态解析切块为细粒度语义（如函数、Impl块），
并提供代码片段级别的向量检索能力，脱离完整的编译环境进行依赖关系与相似度分析。
"""
import os
import json
import logging
import numpy as np
from typing import List, Dict, Any, Optional

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

logger = logging.getLogger("code_rag")

class CodeChunk:
    def __init__(self, file_path: str, start_line: int, end_line: int, code: str, node_type: str, name: str = ""):
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.code = code
        self.node_type = node_type
        self.name = name

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "code": self.code,
            "node_type": self.node_type,
            "name": self.name
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CodeChunk":
        return cls(**d)

class ASTParser:
    """封装 Tree-sitter 的代码 AST 解析器。"""
    def __init__(self):
        self.langs = {}
        try:
            import tree_sitter_c
            import tree_sitter_rust
            from tree_sitter import Language, Parser
            self.langs['c'] = Language(tree_sitter_c.language())
            self.langs['rust'] = Language(tree_sitter_rust.language())
            self.Parser = Parser
            logger.info("AST 解析器: tree-sitter 加载成功")
        except ImportError as e:
            logger.warning(f"AST 解析器: tree-sitter 加载失败 ({e})，将使用正则表达式进行基础降级降级切块。")
            self.langs = None

    def parse_file(self, file_path: str) -> List[CodeChunk]:
        if not os.path.exists(file_path):
            return []
            
        ext = os.path.splitext(file_path)[1].lower()
        if ext in ['.c', '.h']:
            lang_key = 'c'
        elif ext in ['.rs']:
            lang_key = 'rust'
        else:
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code_bytes = f.read().encode('utf-8')
        except UnicodeDecodeError:
            return []

        if self.langs and lang_key in self.langs:
            return self._parse_with_treesitter(file_path, code_bytes, lang_key)
        else:
            return self._parse_with_regex(file_path, code_bytes.decode('utf-8', errors='ignore'), lang_key)

    def _parse_with_treesitter(self, file_path: str, code_bytes: bytes, lang_key: str) -> List[CodeChunk]:
        parser = self.Parser(self.langs[lang_key])
        tree = parser.parse(code_bytes)
        root_node = tree.root_node
        
        chunks = []
        
        # 简单的遍历提取函数定义和 impl/struct
        def traverse(node):
            if lang_key == 'rust' and node.type in ['function_item', 'impl_item', 'struct_item']:
                name = ""
                # 尝试查找名字
                for child in node.children:
                    if child.type == 'identifier' or child.type == 'type_identifier':
                        name = code_bytes[child.start_byte:child.end_byte].decode('utf-8')
                        break
                
                chunk_code = code_bytes[node.start_byte:node.end_byte].decode('utf-8')
                chunks.append(CodeChunk(file_path, node.start_point[0] + 1, node.end_point[0] + 1, chunk_code, node.type, name))
                return # 假设不再进入下层嵌套以避免切块过碎
                
            elif lang_key == 'c' and node.type in ['function_definition', 'struct_specifier']:
                name = ""
                # C语言名字查找相对复杂，简单粗暴截取一下声明
                if node.type == 'function_definition':
                    for child in node.children:
                        if child.type == 'function_declarator':
                            for sc in child.children:
                                if sc.type == 'identifier':
                                    name = code_bytes[sc.start_byte:sc.end_byte].decode('utf-8')
                                    break
                
                chunk_code = code_bytes[node.start_byte:node.end_byte].decode('utf-8')
                chunks.append(CodeChunk(file_path, node.start_point[0] + 1, node.end_point[0] + 1, chunk_code, node.type, name))
                return
                
            for child in node.children:
                traverse(child)
                
        traverse(root_node)
        return chunks

    def _parse_with_regex(self, file_path: str, code: str, lang_key: str) -> List[CodeChunk]:
        """极为基础的正则表达式降级备份，用于未安装 tree-sitter 的环境"""
        # 仅作为极简 fallback，不保证准确度
        chunks = []
        import re
        if lang_key == 'rust':
            # 匹配 fn 关键字块
            pattern = re.compile(r'^\s*(?:pub\s+)?fn\s+([a-zA-Z0-9_]+)\s*\(.*?\)\s*(?:->\s*.*?)?\s*\{', re.MULTILINE)
        else:
            # 简化的 C 函数匹配
            pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_*\s]*\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^;]*\)\s*\{', re.MULTILINE)

        lines = code.split('\n')
        for match in pattern.finditer(code):
            name = match.group(1)
            start_idx = code[:match.start()].count('\n') + 1
            # 寻找对应的闭合大括号
            open_braces = 0
            end_idx = start_idx
            in_func = False
            for i, line in enumerate(lines[start_idx-1:]):
                open_braces += line.count('{')
                open_braces -= line.count('}')
                if open_braces > 0:
                    in_func = True
                if in_func and open_braces == 0:
                    end_idx = start_idx + i
                    break
            
            chunk_code = "\n".join(lines[start_idx-1:end_idx])
            chunks.append(CodeChunk(file_path, start_idx, end_idx, chunk_code, "function_regex", name))
            
        return chunks

class CodeRAGEngine:
    def __init__(self, project_name: str, output_dir: str = "./output"):
        self.project_name = project_name
        self.db_dir = os.path.join(output_dir, project_name, "_vector_db")
        os.makedirs(self.db_dir, exist_ok=True)
        self.chunks_file = os.path.join(self.db_dir, "chunks.json")
        self.vectors_file = os.path.join(self.db_dir, "vectors.npy")
        
        self.chunks: List[CodeChunk] = []
        self.vectors: Optional[np.ndarray] = None
        self.model = None

    def _load_model(self):
        if self.model is None and SentenceTransformer is not None:
            # 使用针对代码优化的模型，或回退到通用模型
            model_name = os.environ.get("CODE_EMBEDDING_MODEL", "jinaai/jina-embeddings-v2-base-code")
            try:
                self.model = SentenceTransformer(model_name, trust_remote_code=True)
            except Exception as e:
                logger.warning(f"无法加载代码模型 {model_name}: {e}，尝试使用 BAAI/bge-m3")
                self.model = SentenceTransformer("BAAI/bge-m3")

    def build_index(self, repo_path: str, force: bool = False):
        if not force and os.path.exists(self.chunks_file) and os.path.exists(self.vectors_file):
            logger.info("发现现有向量索引，直接加载...")
            self.load()
            return
            
        logger.info(f"正在扫描 {repo_path} 解析 AST 代码块...")
        parser = ASTParser()
        all_chunks = []
        
        for root, _, files in os.walk(repo_path):
            if '.git' in root or 'target' in root or 'build' in root:
                continue
            for file in files:
                if file.endswith(('.c', '.h', '.rs')):
                    file_path = os.path.join(root, file)
                    file_chunks = parser.parse_file(file_path)
                    all_chunks.extend(file_chunks)
                    
        self.chunks = all_chunks
        logger.info(f"解析完成：共提取 {len(self.chunks)} 个代码块。")
        
        if len(self.chunks) == 0:
            return
            
        self._load_model()
        if self.model:
            logger.info("正在生成代码向量...")
            texts = [f"Name: {c.name}\nPath: {c.file_path}\nType: {c.node_type}\nCode:\n{c.code[:2000]}" for c in self.chunks]
            self.vectors = self.model.encode(texts, normalize_embeddings=True)
            self.vectors = np.array(self.vectors, dtype=np.float32)
            self.save()
            logger.info("代码向量生成完毕并保存。")
        else:
            logger.warning("未检测到 SentenceTransformers，无法生成向量。只保存代码块文本。")
            self.save()

    def save(self):
        with open(self.chunks_file, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in self.chunks], f, ensure_ascii=False, indent=2)
        if self.vectors is not None:
            np.save(self.vectors_file, self.vectors)

    def load(self):
        with open(self.chunks_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            self.chunks = [CodeChunk.from_dict(d) for d in data]
        if os.path.exists(self.vectors_file):
            self.vectors = np.load(self.vectors_file)

    def search(self, query: str, top_k: int = 3) -> List[Dict[str, Any]]:
        if not self.chunks:
            return []
            
        if self.vectors is not None:
            self._load_model()
            q_vec = self.model.encode([query], normalize_embeddings=True)[0]
            scores = np.dot(self.vectors, q_vec)
            top_indices = np.argsort(scores)[-top_k:][::-1]
            
            results = []
            for idx in top_indices:
                score = float(scores[idx])
                chunk = self.chunks[idx].to_dict()
                chunk["similarity_score"] = score
                results.append(chunk)
            return results
        else:
            # 如果没有向量搜索，极其简陋的文本搜索降级
            query_terms = query.lower().split()
            scored_chunks = []
            for chunk in self.chunks:
                text = f"{chunk.name} {chunk.code}".lower()
                score = sum(1 for t in query_terms if t in text)
                if score > 0:
                    scored_chunks.append((score, chunk))
            
            scored_chunks.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, chunk in scored_chunks[:top_k]:
                c_dict = chunk.to_dict()
                c_dict["similarity_score"] = score
                results.append(c_dict)
            return results
