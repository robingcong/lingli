"""Milvus vector helper utilities."""

import os

from django.conf import settings
from pymilvus import Collection, connections, utility
from sentence_transformers import SentenceTransformer
from unstructured.chunking.basic import chunk_elements
from unstructured.chunking.title import chunk_by_title
from unstructured.partition.auto import partition
from unstructured.partition.xlsx import partition_xlsx

from apps.knowledge.vector_store import MilvusVectorStore
from utils.logger_manager import get_logger

logger = get_logger(__name__)

_embedding_model = None


def get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer("BAAI/bge-m3", trust_remote_code=True)
    return _embedding_model


def init_milvus_collection(collection_name=None):
    """初始化Milvus集合"""
    logger.info("进入init_milvus_collection方法")
    try:
        vector_cfg = getattr(settings, "VECTOR_DB_CONFIG", {})
        host = vector_cfg.get("host", os.getenv("MILVUS_HOST", "127.0.0.1"))
        port = vector_cfg.get("port", os.getenv("MILVUS_PORT", "19530"))
        collection_name = collection_name or vector_cfg.get(
            "collection_name", os.getenv("MILVUS_COLLECTION", "vv_rag_markdown_chunks")
        )

        connections.connect(host=host, port=port)

        if utility.has_collection(collection_name):
            return Collection(name=collection_name)

        MilvusVectorStore(host=host, port=port, collection_name=collection_name)
        collection = Collection(name=collection_name)
        collection.load()
        return collection
    except Exception as e:
        raise Exception(f"初始化Milvus集合失败: {str(e)}")


def process_single_excel(file_path):
    """处理单个Excel文件"""
    try:
        elements = partition_xlsx(filename=file_path)
        chunks = chunk_elements(elements=elements, max_characters=500)
    except Exception as e:
        raise ValueError(f"Excel文件处理失败: {str(e)}")
    return chunks


def process_single_pdf(file_path):
    """处理单个pdf文件"""
    try:
        elements = partition(filename=file_path)
        chunks = chunk_by_title(
            elements,
            max_characters=500,
            combine_text_under_n_chars=200,
            multipage_sections=True,
        )
    except Exception as e:
        raise ValueError(f"PDF文件处理失败: {str(e)}")
    return chunks


def process_singel_file(file_path):
    """处理单个文件, 返回文件分区/chunking后的chunks"""
    file_categories = {
        "CSV": [".csv"],
        "E-mail": [".eml", ".msg", ".p7s"],
        "EPUB": [".epub"],
        "Excel": [".xls", ".xlsx"],
        "HTML": [".html"],
        "Image": [".bmp", ".heic", ".jpeg", ".png", ".tiff"],
        "Markdown": [".md"],
        "Org Mode": [".org"],
        "Open Office": [".odt"],
        "PDF": [".pdf"],
        "Plain text": [".txt"],
        "PowerPoint": [".ppt", ".pptx"],
        "reStructured Text": [".rst"],
        "Rich Text": [".rtf"],
        "TSV": [".tsv"],
        "Word": [".doc", ".docx"],
        "XML": [".xml"],
    }

    file_type = os.path.splitext(file_path)[1]
    for _, types in file_categories.items():
        if file_type in types:
            logger.info(f"开始解析文件: {file_path}")
            try:
                if file_type in [".xlsx", ".xls"]:
                    chunks = process_single_excel(file_path)
                elif file_type in [".pdf"]:
                    chunks = process_single_pdf(file_path)
                else:
                    elements = partition(filename=file_path)
                    chunks = chunk_by_title(elements=elements, max_characters=500)
                logger.info("文件调用unstructured库分区/chunking成功")
                return chunks
            except Exception as e:
                logger.error(f"文件调用unstructured库分区/chunking失败: {str(e)}")
                return None

    raise ValueError(f"不支持的文件类型: {file_type}")
