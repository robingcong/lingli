from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, FileResponse
from django.views.decorators.http import require_http_methods
import json

from .models import (
    TestCase,
    TestCaseReview,
    KnowledgeBase,
    TestCaseAIReview,
    PRDAnalysis,
    ApiSchemaFile,
    ApiCaseGeneration,
)
from .forms import TestCaseForm, TestCaseReviewForm, KnowledgeBaseForm
from ..agents.generator import TestCaseGeneratorAgent
from ..agents.reviewer import TestCaseReviewerAgent
from ..agents.analyser import PrdAnalyserAgent
from ..agents.api_case_generator import APITestCaseGeneratorAgent, parse_api_definitions, generate_test_cases_for_apis
from ..agents.prompts import APITestCaseGeneratorPrompt
from ..agents.progress_registry import get_progress as get_task_progress
from ..knowledge.service import KnowledgeService
from .title_utils import build_test_case_title

from django.conf import settings
from apps.llm import LLMServiceFactory
from ..knowledge.vector_store import MilvusVectorStore
from ..knowledge.embedding import BGEM3Embedder
from utils.logger_manager import get_logger, set_task_context, clear_task_context

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import os
from datetime import datetime
import time
from .milvus_helper import get_embedding_model, init_milvus_collection, process_singel_file
from langchain.text_splitter import CharacterTextSplitter
import hashlib
import numpy as np
import gc
import xlwt
from django.http import HttpResponse
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from utils.file_transfer import word_to_markdown

logger = get_logger(__name__)

llm_config = getattr(settings, 'LLM_PROVIDERS', {})

DEFAULT_PROVIDER = llm_config.get('default_provider', 'deepseek')

PROVIDERS = {k: v for k, v in llm_config.items() if k != 'default_provider'}

DEFAULT_LLM_CONFIG = PROVIDERS.get(DEFAULT_PROVIDER, {})

llm_service = LLMServiceFactory.create(
    provider=DEFAULT_PROVIDER,
    **DEFAULT_LLM_CONFIG
)
FRONTEND_BASE_URL = os.getenv("FRONTEND_BASE_URL", "http://127.0.0.1:5173").rstrip("/")


def _redirect_to_frontend(path: str):
    route = path if path.startswith("/") else f"/{path}"
    return redirect(f"{FRONTEND_BASE_URL}{route}")

class _FallbackKnowledgeService:
    """Milvus不可用时的降级服务，避免应用启动失败。"""

    def add_knowledge(self, title, content):
        item = KnowledgeBase(title=title, content=content)
        item.save()
        return item.id

    def search_knowledge(self, query):
        return []

    def search_relevant_knowledge(self, query, top_k=5, min_score_threshold=0.6):
        return ""


try:
    vector_cfg = getattr(settings, 'VECTOR_DB_CONFIG', {})
    if getattr(settings, 'ENABLE_MILVUS', True) and vector_cfg:
        vector_store = MilvusVectorStore(
            host=vector_cfg['host'],
            port=vector_cfg['port'],
            collection_name=vector_cfg['collection_name']
        )
        embedder = BGEM3Embedder(
            model_name="BAAI/bge-m3"
        )
        knowledge_service = KnowledgeService(vector_store, embedder)
    else:
        logger.warning("Milvus disabled or VECTOR_DB_CONFIG missing, using fallback knowledge service.")
        knowledge_service = _FallbackKnowledgeService()
except Exception as exc:
    logger.warning(f"Milvus init failed, using fallback knowledge service: {exc}")
    knowledge_service = _FallbackKnowledgeService()
# test_case_generator = TestCaseGeneratorAgent(llm_service, knowledge_service)
#test_case_reviewer = TestCaseReviewerAgent(llm_service, knowledge_service)

def index(request):
    """页面-首页视图"""
    return JsonResponse({
        'success': True,
        'message': '后端服务已启动，请使用前端 SPA 访问。'
    })

def generate(request):
    """
    测试用例生成视图
    """
    logger.info("===== 进入 generate 视图 =====")
    logger.info(f"请求方法: {request.method}")
    context = {
        'llm_providers': PROVIDERS,
        'llm_provider': DEFAULT_PROVIDER,
        'requirement': '',
        # 'api_description': '',
        'test_cases': None  # 初始化为 None
    }
    
    if request.method == 'GET':
        return _redirect_to_frontend('/generate')
    
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        logger.error("JSON解析错误", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据'
        }, status=400)
    
    requirements = data.get('requirements', '')
    if not requirements:
        return JsonResponse({
            'success': False,
            'message': '需求描述不能为空'
        })

    llm_provider = data.get('llm_provider', DEFAULT_PROVIDER)

    default_case_design_methods = [
        '等价类划分',
        '边界值分析',
        '判定表',
        '因果图',
        '正交分析',
        '场景法'
    ]
    default_case_categories = [
        '功能测试',
        '性能测试',
        '兼容性测试',
        '安全测试'
    ]

    case_design_methods = data.get('case_design_methods') or default_case_design_methods
    case_categories = data.get('case_categories') or default_case_categories
    case_count = int(data.get('case_count', 0))
    generation_quality_config = dict(getattr(settings, "TEST_CASE_GENERATION_CONFIG", {}))
    
    logger.info(f"接收到的数据: {json.dumps(data, ensure_ascii=False)}")
    
    try:
        logger.info(f"使用 {llm_provider} 生成测试用例...")
        provider_config = dict(PROVIDERS.get(llm_provider, {}))
        provider_config.pop("temperature", None)
        llm_service = LLMServiceFactory.create(
            llm_provider,
            **provider_config,
            temperature=generation_quality_config.get("generation_temperature", 0.3),
        )
        reviewer_llm_service = LLMServiceFactory.create(
            llm_provider,
            **provider_config,
            temperature=generation_quality_config.get("review_temperature", 0.2),
        )
        reviewer_agent = TestCaseReviewerAgent(reviewer_llm_service, knowledge_service)
        generator_agent = TestCaseGeneratorAgent(
            llm_service=llm_service,
            knowledge_service=knowledge_service,
            case_design_methods=case_design_methods,
            case_categories=case_categories,
            case_count=case_count,
            reviewer_agent=reviewer_agent,
            quality_config=generation_quality_config,
        )
        logger.info(f"开始生成测试用例- 需求: {requirements}...")
        logger.info(f"选择的用例设计方法 {case_design_methods}")
        logger.info(f"选择的用例类型 {case_categories}")
        logger.info(f"生成用例条数: {case_count}")
        
        test_cases = generator_agent.generate(requirements, input_type="requirement")
        logger.info(f"测试用例生成成功 - 生成数量: {len(test_cases)}")
        
        context.update({
            'test_cases': test_cases
        })
        
        return JsonResponse({
            'success': True,
            'test_cases': test_cases
        })
            
    except Exception as e:
        logger.error(f"生成测试用例时出错 {str(e)}", exc_info=True)
        err_msg = str(e)
        if "Insufficient Balance" in err_msg or "Payment Required" in err_msg or "402" in err_msg:
            user_msg = "调用大模型失败：余额不足，请充值或切换到可用模型"
        else:
            user_msg = f"调用失败：{err_msg}"
        return JsonResponse({
            'success': False,
            'message': user_msg
        }, status=500)

def format_test_cases_to_html(test_cases):
    """将测试用例列表转换为HTML"""
    html = ""
    for i, test_case in enumerate(test_cases):
        html += f"<div class='test-case mb-4'>"
        html += f"<h4>测试用例 #{i+1}: {test_case.get('description', '无描述')}</h4>"
        
        html += "<div class='test-steps mb-3'>"
        html += "<h5>测试步骤:</h5>"
        html += "<ol>"
        for step in test_case.get('test_steps', []):
            html += f"<li>{step}</li>"
        html += "</ol>"
        html += "</div>"
        
        html += "<div class='expected-results'>"
        html += "<h5>预期结果:</h5>"
        html += "<ol>"
        for result in test_case.get('expected_results', []):
            html += f"<li>{result}</li>"
        html += "</ol>"
        html += "</div>"
        
        html += "</div>"
    
    return html



@require_http_methods(["POST"])
def save_test_case(request):
    """保存测试用例到数据库"""
    try:
        data = json.loads(request.body)
        requirement = data.get('requirement')
        test_cases_list = data.get('test_cases', [])
        llm_provider = data.get('llm_provider')
        
        
        if not test_cases_list:
            return JsonResponse({
                'success': False,
                'message': '测试用例数据不能为空'
            }, status=400)
        
        test_cases_to_create = []
        
        for index, test_case in enumerate(test_cases_list, 1):
            test_case_instance = TestCase(
                title=build_test_case_title(
                    description=test_case.get('description', ''),
                    fallback_title=f"测试用例-{index}",
                ),
                description=test_case.get('description', ''),
                test_steps='\n'.join(test_case.get('test_steps', [])),
                expected_results='\n'.join(test_case.get('expected_results', [])),
                requirements=requirement,
                llm_provider=llm_provider,
                status='pending'  # 默认状态为待审核
            )
            test_cases_to_create.append(test_case_instance)
        
        created_test_cases = TestCase.objects.bulk_create(test_cases_to_create)
        
        logger.info(f"成功保存 {len(created_test_cases)} 条测试用例")
        
        return JsonResponse({
            'success': True,
            'message': f'成功保存 {len(created_test_cases)} 条测试用例',
            'test_case_id': [case.id for case in created_test_cases]
        })
        
    except json.JSONDecodeError:
        logger.error("JSON瑙ｆ瀽閿欒", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据'
        }, status=400)
    except Exception as e:
        logger.error(f"保存测试用例时出错 {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'保存失败：{str(e)}'
        }, status=500)

def review_view(request):
    """页面-测试用例审核页面渲染"""
    return _redirect_to_frontend('/review')

@require_http_methods(["POST"])
def case_review(request):
    """测试用例审核API接口"""
    try:
        data = json.loads(request.body)
        test_case_id = data.get('test_case_id')
        
        logger.info(f"收到测试用例审核请求 - 测试用例ID: {test_case_id}")
        
        if not test_case_id:
            logger.error("测试用例ID不能为空")
            return JsonResponse({
                'success': False,
                'message': '测试用例ID不能为空'
            }, status=400)
            
        try:
            test_case = TestCase.objects.get(id=test_case_id)
            logger.info(f"找到测试用例: ID={test_case.id}")
        except TestCase.DoesNotExist:
            logger.error(f"找不到ID为{test_case_id}的测试用例")
            return JsonResponse({
                'success': False,
                'message': f'找不到ID为{test_case_id}的测试用例'
            }, status=404)
        
        logger.info("调用测试用例审核Agent...")
        test_case_reviewer = TestCaseReviewerAgent(llm_service, knowledge_service)
        review_payload = test_case_reviewer.review_case_data(
            {
                "description": test_case.description,
                "test_steps": test_case.test_steps,
                "expected_results": test_case.expected_results,
            }
        )
        review_content = review_payload["raw_text"]
        score = review_payload.get("score")
        recommendation = review_payload.get("recommendation", "")
        logger.info(f"审核完成，结果: {review_content}")

        TestCaseAIReview.objects.update_or_create(
            test_case=test_case,
            defaults={
                "provider": DEFAULT_PROVIDER,
                "score": score,
                "recommendation": recommendation,
                "raw_result": review_content
            }
        )

        return JsonResponse({
            'success': True,
            'review_result': review_content  # 审核结果的原始内容
        })
        
    except json.JSONDecodeError:
        logger.error("JSON解析错误", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': '无效的JSON数据'
        }, status=400)
    except Exception as e:
        logger.error(f"测试用例审核时出错 {str(e)}", exc_info=True)
        err_msg = str(e)
        if "Insufficient Balance" in err_msg or "Payment Required" in err_msg or "402" in err_msg:
            user_msg = "调用大模型失败：余额不足，请充值或切换到可用模型"
        else:
            user_msg = f"调用大模型失败：{err_msg}"
        return JsonResponse({
            'success': False,
            'message': user_msg
        }, status=500)


def knowledge_view(request):
    """知识库管理页面"""
    return _redirect_to_frontend('/knowledge')

@require_http_methods(["POST"])
def add_knowledge(request):
    """添加知识条目"""
    try:
        data = json.loads(request.body)
        title = data.get('title')
        content = data.get('content')
        
        if not title or not content:
            return JsonResponse({
                'success': False,
                'message': '标题和内容不能为空'
            })
        
        knowledge_id = knowledge_service.add_knowledge(title, content)
        
        return JsonResponse({
            'success': True,
            'message': '知识条目添加成功',
            'knowledge_id': knowledge_id
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

def knowledge_list(request):
    """获取知识库条目"""
    try:
        knowledge_items = KnowledgeBase.objects.all().order_by('-created_at')
        
        items = []
        for item in knowledge_items:
            items.append({
                'id': item.id,
                'title': item.title,
                'content': item.content,
                'created_at': item.created_at.isoformat()
            })
        
        return JsonResponse({
            'success': True,
            'knowledge_items': items
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@require_http_methods(["POST"])
def search_knowledge(request):
    """搜索知识库"""
    try:
        data = json.loads(request.body)
        query = data.get('query')
        
        if not query:
            return JsonResponse({
                'success': False,
                'message': '搜索关键词不能为空'
            })
        
        query_embedding = embedder.get_embeddings(query)[0]
        logger.info(f"查询文本: '{query}', 向量长度: {len(query_embedding)}, 前五个维度: {query_embedding[:5]}")
        results = knowledge_service.search_knowledge(query)
        
        return JsonResponse({
            'success': True,
            'results': results
        })
    except Exception as e:
        return JsonResponse({
            'success': False,
            'message': str(e)
        })

@csrf_exempt
def upload_single_file(request):
    """处理文件上传的接口"""
    if request.method == 'GET':
        return _redirect_to_frontend('/upload')
    elif request.method == 'POST':
        if 'single_file' in request.FILES:  # 修改这里对应上传文件的name 属性
            uploaded_file = request.FILES['single_file']  # 修改这里对应上传文件的name 属性
            file_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.name)
            
            if os.path.exists(file_path):
                return JsonResponse({
                    'success': False,
                    'error': '文件已存在'
                })
                
            try:
                logger.info(f"Uploaded file: {uploaded_file}")
                if not uploaded_file:
                    return JsonResponse({'success': False, 'error': '未直接找到文件'})
                
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
                    "XML": [".xml"]
                }
                file_type = os.path.splitext(uploaded_file.name)[1]
                logger.info(f"上传文件类型: {file_type}")
                logger.info(f"上传文件名: {uploaded_file.name}")
                
                if not file_type:
                    logger.error("文件没有扩展名")
                    return JsonResponse({'success': False, 'error': '文件必须包含扩展名'})
                
                supported_extensions = [ext.lower() for exts in file_categories.values() for ext in exts]

                if file_type not in supported_extensions:
                    return JsonResponse({'success': False, 'error': '不支持的文件类型'})
                
                save_dir = 'uploads/'
                os.makedirs(save_dir, exist_ok=True)
                file_path = os.path.join(save_dir, f"{uploaded_file.name}")
                with open(file_path, 'wb+') as f:
                    for chunk in uploaded_file.chunks():
                        f.write(chunk)
                logger.info(f"临时文件保存成功, 文件保存路径: {file_path}")

                chunks = process_singel_file(file_path)  # 获取初始数据和文本切分结果
                if not chunks:
                    return JsonResponse({'success': False, 'error': '文件没有有效内容可供处理'})

                if isinstance(chunks, list):
                    text_contents = []
                    for i, chunk in enumerate(chunks):
                        if hasattr(chunk, 'text'):
                            text_contents.append(str(chunk.text))
                        else:
                            text_contents.append(str(chunk))
                
                    logger.info(f"提取到 {len(text_contents)} 段文本内容")
                else:
                    if hasattr(chunks, 'text'):
                        text_contents = [str(chunks.text)]
                    else:
                        text_contents = [str(chunks)]
                    logger.info(f"提取到单段文本内容 {text_contents[0][:100]}...")

                logger.info("开始生成向量")
                start_time = datetime.now()

                try:
                    all_embeddings = embedder.get_embeddings(texts=text_contents, show_progress_bar=False)
                    logger.info(f"成功生成 {len(all_embeddings)} 段向量")
                    
                    embeddings_list = []
                    for emb in all_embeddings:
                        if hasattr(emb, 'tolist'):
                            emb = emb.tolist()
                        embeddings_list.append(emb)
                    
                    data_to_insert = []
                    for i in range(len(text_contents)):
                        item = {
                            "embedding": embeddings_list[i],  # 单个embedding向量
                            "content": text_contents[i],      # 文本内容
                            "metadata": '{}',                 # 元数据
                            "source": file_path,              # 来源
                            "doc_type": file_type,            # 文档类型
                            "chunk_id": f"{hashlib.md5(os.path.basename(file_path).encode()).hexdigest()[:10]}_{i:04d}",  # 块ID
                            "upload_time": datetime.now().isoformat()  # 上传时间
                        }
                        data_to_insert.append(item)
                    
                    logger.info(f"准备向milvus插入{len(data_to_insert)} 条数据")
                    vector_store.add_data(data_to_insert)
                    logger.info("数据插入完成")
                    
                    total_time = (datetime.now() - start_time).total_seconds()
                    logger.info(f"向量生成和数据插入总耗时: {total_time:.2f} 秒")
                    
                    return JsonResponse({
                        'success': True, 
                        'count': len(text_contents),
                        'message': f'成功导入文件到知识库'
                    })
                    
                except Exception as e:
                    logger.error(f"生成和导入向量时出错: {str(e)}", exc_info=True)
                    return JsonResponse({
                        'success': False, 
                        'error': str(e)
                    })
                
            except Exception as e:
                logger.error(f"处理上传文件时出错: {str(e)}", exc_info=True)
                return JsonResponse({
                    'success': False, 
                    'error': str(e)
                })
            finally:
                if os.path.exists(file_path):
                    pass
                    # os.remove(file_path)
        else:
            return JsonResponse({
                'success': False,
                'error': '未能找到文件'
            })
    
    return JsonResponse({
        'success': False,
        'error': '不支持的请求方法'
    })


def case_review_detail(request):
    return _redirect_to_frontend('/review')

@require_http_methods(["GET"])
def get_test_case(request, test_case_id):
    """从Mysql查询、获取单个测试用例"""
    try:
        test_case = TestCase.objects.get(id=test_case_id)
        ai_review = None
        if hasattr(test_case, "ai_review"):
            ai_review = test_case.ai_review
        return JsonResponse({
            'id': test_case.id,
            'description': test_case.description,
            'test_steps': test_case.test_steps,
            'expected_results': test_case.expected_results,
            'status': test_case.status,
            'ai_review': {
                'provider': ai_review.provider,
                'score': ai_review.score,
                'recommendation': ai_review.recommendation,
                'raw_result': ai_review.raw_result,
                'updated_at': ai_review.updated_at.isoformat()
            } if ai_review else None
        })
    except TestCase.DoesNotExist:
        return JsonResponse({'error': '测试用例不存在'}, status=404)
    
    
def get_test_cases(request, test_case_ids: str):
    """从Mysql查询、获取多个测试用例"""
    try:
        ids = test_case_ids.split(',')
        test_cases = TestCase.objects.filter(id__in=ids).values(
                    'id', 'title', 'description', 'test_steps', 
                    'expected_results', 'status', 'requirements', 'llm_provider'
                )
        logger.info(f"获取到的测试用例集合数据类型是 {type(test_cases)}")
        return JsonResponse({
            'success': True,
            'test_cases': list(test_cases)
        })
    except TestCase.DoesNotExist:
        return JsonResponse({'error': '测试用例集合不存在'}, status=404)
    

@require_http_methods(["POST"])
def update_test_case(request):
    data = json.loads(request.body)
    logger.info(f"更新测试用例数据: {data}")
    try:
        test_case = TestCase.objects.get(id=data['test_case_id'])
        test_case.status = data['status']
        test_case.description = data['description']
        test_case.test_steps = data['test_steps']
        test_case.expected_results = data['expected_results']
        test_case.save()
        return JsonResponse({'success': True})
    except TestCase.DoesNotExist:
        return JsonResponse({'success': False, 'message': '测试用例不存在'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}) 


def copy_test_cases(request):
    """返回用户移动复制后的测试用例数据"""
    try:
        ids = request.GET.get('ids')
        response = get_test_cases(request,ids)
        response_data = json.loads(response.content)
        if response_data.get('success'):
            test_cases = response_data.get('test_cases')
            logger.info(f"获取到的测试用例集合数据类型是 222: {type(test_cases)}")
            return JsonResponse({
                'success': True,
                'test_cases': test_cases
            })
        else:
            return JsonResponse({
                'success': False,
                'message': response_data.get('message')
            })
    except TestCase.DoesNotExist:
        return JsonResponse({'error': '测试用例集合不存在'}, status=404)
    
def export_test_cases_excel(request):
    """将测试用例导出到excel"""
    try:
        ids = request.GET.get('ids')
        if not ids:
            return JsonResponse({'success': False, 'message': '未提供测试用例ID'})
            
        response = get_test_cases(request, ids)
        response_data = json.loads(response.content)
        
        if not response_data.get('success'):
            return JsonResponse({'success': False, 'message': '获取测试用例数据失败'})
            
        test_cases = response_data.get('test_cases')
        logger.info(f"获取到的测试用例集合数据类型是 {type(test_cases)}")
        
        wb = xlwt.Workbook(encoding='utf-8')
        ws = wb.add_sheet('测试用例')
        
        header_style = xlwt.XFStyle()
        header_font = xlwt.Font()
        header_font.bold = True
        header_style.font = header_font
        
        headers = ['编号', '用例描述', '测试步骤', '预期结果', '状态']
        for col, header in enumerate(headers):
            ws.write(0, col, header, header_style)
            ws.col(col).width = 256 * 30  # 30字符宽度
        
        for row, test_case in enumerate(test_cases, start=1):
            ws.write(row, 0, row)  # 编号
            ws.write(row, 1, test_case.get('description', ''))
            ws.write(row, 2, test_case.get('test_steps', ''))
            ws.write(row, 3, test_case.get('expected_results', ''))
            ws.write(row, 4, test_case.get('status', ''))
            
            ws.row(row).height_mismatch = True
            ws.row(row).height = 20 * 40  # 40字符高度
        
        current_time = datetime.now().strftime('%Y%m%d_%H%M%S')  # 格式：20240319_153021
        case_count = len(test_cases)
        filename = f"test_cases_{current_time}_{case_count}_cases.xls"
        
        response = HttpResponse(content_type='application/vnd.ms-excel')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        wb.save(response)
        return response
        
    except Exception as e:
        logger.error(f"导出Excel失败: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'导出Excel失败: {str(e)}'
        }) 

@require_http_methods(["DELETE"])
def delete_test_cases(request):
    """删除选中的测试用例"""
    try:
        ids = request.GET.get('ids', '')
        if not ids:
            return JsonResponse({'success': False, 'message': '未提供测试用例ID'})
            
        test_case_ids = ids.split(',')
        TestCase.objects.filter(id__in=test_case_ids).delete()
        
        return JsonResponse({
            'success': True,
            'message': f'成功删除 {len(test_case_ids)} 条测试用例'
        })
    except Exception as e:
        logger.error(f"删除测试用例失败: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'message': f'删除失败: {str(e)}'
        }) 
    
def prd_analyser(request):
    """从PRD文件生成测试用例&测试场景"""
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'message': '后端服务已启动，请使用前端 SPA 访问 /analyser 页面。'
        })
    elif request.method == 'POST':
        if 'single_file' in request.FILES:  # 修改这里根据上传的文件的name 属性
            uploaded_file = request.FILES['single_file']  # 修改这里根据上传的文件的name 属性
            file_path = os.path.join(settings.MEDIA_ROOT, uploaded_file.name)
            if os.path.exists(file_path):
                return JsonResponse({
                    'success': False,
                    'error': '文件已存在'
                })
            logger.info(f"Uploaded file: {uploaded_file}")
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': '未能找到文件'})
            file_type = os.path.splitext(uploaded_file.name)[1]
            if file_type != '.docx':
                return JsonResponse({'success': False, 'error': '不支持的文件类型'})
            logger.info(f"上传文件类型: {file_type}")
            logger.info(f"上传文件名: {uploaded_file.name}")
            save_dir = 'prd/'
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, f"{uploaded_file.name}")
            with open(file_path, 'wb+') as f:
                for chunk in uploaded_file.chunks():
                    f.write(chunk)
            logger.info(f"临时文件保存成功, 文件保存路径: {file_path}")
            md_path = file_path.replace('.docx', '.md')
            ok = word_to_markdown(file_path, md_path)
            if not ok or not os.path.exists(md_path):
                return JsonResponse({
                    'success': False,
                    'error': '文档转换失败：未检测到 pandoc。请安装 pandoc 并加入 PATH。'
                })
            with open(md_path, 'r', encoding='utf-8') as f:
                prd_content = f.read()
            logger.info(f"PRD内容: {prd_content}")
            analyser = PrdAnalyserAgent(llm_service=llm_service)
            result = analyser.analyse(prd_content)
            analysis_result = result
            if not isinstance(result, str):
                analysis_result = json.dumps(result, ensure_ascii=False)
            record = PRDAnalysis.objects.create(
                file_name=uploaded_file.name,
                prd_content=prd_content,
                analysis_result=analysis_result
            )
            return JsonResponse({
                'success': True,
                'result': result,
                'prd_content': prd_content,
                'prd_id': record.id
            })
        else:
            return JsonResponse({
                'success': False,
                'error': '未能找到文件'
            })
        return JsonResponse({
        'success': False,
        'error': '不支持的请求方法'
    })


@require_http_methods(["GET"])
def prd_analysis_list(request):
    """获取 PRD 分析历史列表"""
    items = PRDAnalysis.objects.all().order_by('-created_at')
    data = [
        {
            'id': item.id,
            'file_name': item.file_name,
            'created_at': item.created_at.isoformat()
        }
        for item in items
    ]
    return JsonResponse({
        'success': True,
        'items': data
    })


@require_http_methods(["GET", "DELETE"])
def prd_analysis_detail(request, analysis_id: int):
    """?? PRD ????/??"""
    try:
        item = PRDAnalysis.objects.get(id=analysis_id)
    except PRDAnalysis.DoesNotExist:
        return JsonResponse({'success': False, 'message': '?????'}, status=404)

    if request.method == "DELETE":
        item.delete()
        return JsonResponse({
            'success': True,
            'message': '????'
        })

    return JsonResponse({
        'success': True,
        'item': {
            'id': item.id,
            'file_name': item.file_name,
            'prd_content': item.prd_content,
            'analysis_result': item.analysis_result,
            'created_at': item.created_at.isoformat(),
            'updated_at': item.updated_at.isoformat()
        }
    })


def download_file(request):
    """文件下载函数"""
    file_path = request.GET.get('file_path')
    if not file_path or not os.path.exists(file_path):
        return JsonResponse({'error': '文件不存在'}, status=404)
    
    uploads_dir = os.path.abspath('uploads')
    file_abs_path = os.path.abspath(file_path)
    
    if not file_abs_path.startswith(uploads_dir):
        return JsonResponse({'error': '访问被拒绝'}, status=404)
    
    filename = os.path.basename(file_path)
    resp = FileResponse(open(file_path, 'rb'), as_attachment=True, filename=filename)
    resp['Content-Type'] = 'application/octet-stream'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp


def _extract_field_schema_from_api_defs(api_definitions):
    """提取字段+字段类型（按接口维度汇总）"""
    schema = []

    def _infer_type(value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "string"

    def _extract_params(params, location):
        fields = []
        if not isinstance(params, list):
            return fields
        for p in params:
            if not isinstance(p, dict):
                continue
            name = p.get("name") or p.get("key") or p.get("paramName")
            ptype = (
                p.get("type")
                or p.get("dataType")
                or p.get("valueType")
                or p.get("paramType")
            )
            if not ptype and isinstance(p.get("schema"), dict):
                ptype = p["schema"].get("type")
            fields.append({
                "name": name or "",
                "type": ptype or "unknown",
                "location": location
            })
        return fields

    for api in api_definitions or []:
        request = api.get("request") or {}
        fields = []

        fields.extend(_extract_params(request.get("query"), "query"))
        fields.extend(_extract_params(request.get("rest"), "rest"))

        body = request.get("body") or {}
        if isinstance(body, dict) and body.get("bodyType") == "JSON":
            json_body = body.get("jsonBody") or {}
            schema_props = (json_body.get("jsonSchema") or {}).get("properties") or {}
            if isinstance(schema_props, dict) and schema_props:
                for key, meta in schema_props.items():
                    if isinstance(meta, dict):
                        fields.append({
                            "name": key,
                            "type": meta.get("type") or "unknown",
                            "location": "body"
                        })
            else:
                json_value = json_body.get("jsonValue")
                if isinstance(json_value, str) and json_value.strip():
                    try:
                        parsed = json.loads(json_value)
                        if isinstance(parsed, dict):
                            for key, value in parsed.items():
                                fields.append({
                                    "name": key,
                                    "type": _infer_type(value),
                                    "location": "body"
                                })
                    except Exception:
                        pass

        schema.append({
            "path": api.get("path", ""),
            "method": api.get("method", ""),
            "name": api.get("name", ""),
            "fields": fields
        })

    return schema


def _extract_field_schema_from_field_map(field_map):
    """字段+类型JSON转字段结构"""
    if not isinstance(field_map, dict):
        return []
    fields = []
    for key, value in field_map.items():
        fields.append({
            "name": str(key),
            "type": str(value),
            "location": "body"
        })
    return [{
        "path": "/auto-generated",
        "method": "POST",
        "name": "字段类型定义",
        "fields": fields
    }]


def api_case_generate(request):
    """
    页面-接口case生成页面函数
    """
    logger.info("===== 进入api_case_generate页面函数 =====")
    logger.info(f"请求方法: {request.method}")
    
    if request.method == 'GET':
        return JsonResponse({
            'success': True,
            'message': '后端服务已启动，请使用前端 SPA 访问 /api-case-generate 页面。'
        })
    elif request.method == 'POST':
        if 'single_file' in request.FILES:
            uploaded_file = request.FILES['single_file']
            logger.info(f"接收到文件 {uploaded_file.name}")
            
            if not uploaded_file.name.lower().endswith('.json'):
                return JsonResponse({
                    'success': False,
                    'error': '不支持的JSON格式的文件'
                })
            
            try:
                uploads_dir = os.path.join(settings.MEDIA_ROOT)
                os.makedirs(uploads_dir, exist_ok=True)
                
                file_name = uploaded_file.name
                base_name, ext = os.path.splitext(file_name)
                counter = 1
                while os.path.exists(os.path.join(uploads_dir, file_name)):
                    file_name = f"{base_name}_{counter}{ext}"
                    counter += 1
                
                file_path = os.path.join(uploads_dir, file_name)
                with open(file_path, 'wb+') as f:
                    for chunk in uploaded_file.chunks():
                        f.write(chunk)
                
                logger.info(f"文件保存成功: {file_path}")
                
                api_list = parse_api_definitions(file_path)
                with open(file_path, 'r', encoding='utf-8') as f:
                    raw_json = f.read()
                try:
                    parsed = json.loads(raw_json)
                except Exception:
                    parsed = {}
                if isinstance(parsed, dict) and isinstance(parsed.get("apiDefinitions"), list):
                    field_schema = _extract_field_schema_from_api_defs(parsed.get("apiDefinitions", []))
                elif isinstance(parsed, dict) and isinstance(parsed.get("fieldMapping"), dict):
                    field_schema = _extract_field_schema_from_field_map(parsed.get("fieldMapping"))
                elif isinstance(parsed, dict):
                    field_schema = _extract_field_schema_from_field_map(parsed)
                else:
                    field_schema = []
                schema_record = ApiSchemaFile.objects.create(
                    file_name=file_name,
                    file_path=file_path,
                    raw_json=raw_json,
                    field_schema=json.dumps(field_schema, ensure_ascii=False)
                )
                
                auto_generate = request.POST.get('auto_generate') == '1'
                if auto_generate:
                    sync_generate = request.POST.get('sync_generate') == '1'
                    selected_apis = request.POST.get('selected_apis')
                    if selected_apis:
                        try:
                            selected_apis = json.loads(selected_apis)
                        except Exception:
                            selected_apis = []
                    else:
                        selected_apis = [item.get('path') for item in api_list if item.get('path')]

                    if not selected_apis:
                        return JsonResponse({
                            'success': False,
                            'error': '未解析到有效的接口定义，请确认JSON包含 apiDefinitions 列表'
                        })

                    count_per_api = int(request.POST.get('count_per_api', 1))
                    priority = request.POST.get('priority', 'P0')
                    llm_provider = request.POST.get('llm_provider', 'deepseek')
                    rules_override = request.POST.get('rules_override') or None
                    task_id = request.POST.get('task_id') or f"task_{int(time.time()*1000)}_{request.user.id if request.user.is_authenticated else 'anon'}"

                    def _persist_generation(result):
                        if not result or not result.get('success'):
                            return None, None
                        with open(file_path, 'r', encoding='utf-8') as f:
                            updated_json = f.read()
                        # 修复历史数据中的乱码占位
                        updated_json = updated_json.replace("??????", "字段类型定义")
                        generation = ApiCaseGeneration.objects.create(
                            schema_file=schema_record,
                            selected_paths=json.dumps(selected_apis, ensure_ascii=False),
                            count_per_api=count_per_api,
                            priority=priority,
                            llm_provider=llm_provider,
                            rules_override=rules_override or '',
                            task_id=task_id,
                            generated_cases=result.get('generated_cases', 0),
                            selected_api_count=result.get('selected_api_count', 0),
                            result_json=updated_json
                        )
                        return generation, updated_json

                    if sync_generate:
                        try:
                            set_task_context(task_id)
                            result = generate_test_cases_for_apis(
                                file_path, selected_apis, count_per_api, priority, llm_provider, task_id,
                                rules_override=rules_override
                            )
                            if not result or not result.get('success'):
                                return JsonResponse({
                                    'success': False,
                                    'error': result.get('error') if isinstance(result, dict) else '生成失败'
                                })
                            generation, updated_json = _persist_generation(result)
                            return JsonResponse({
                                'success': True,
                                'api_list': api_list,
                                'file_path': file_path,
                                'file_id': schema_record.id,
                                'generation_id': generation.id if generation else None,
                                'result_json': updated_json,
                            })
                        except Exception as e:
                            logger.error(f"同步生成失败: {e}")
                            return JsonResponse({
                                'success': False,
                                'error': f'生成失败: {e}'
                            })
                        finally:
                            clear_task_context()

                    import threading

                    def _bg_job():
                        try:
                            set_task_context(task_id)
                            result = generate_test_cases_for_apis(
                                file_path, selected_apis, count_per_api, priority, llm_provider, task_id,
                                rules_override=rules_override
                            )
                            generation, _ = _persist_generation(result)
                            if generation:
                                try:
                                    from ..agents.progress_registry import set_progress as _set_progress
                                    _set_progress(task_id, {
                                        'generation_id': generation.id
                                    })
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"后台生成失败: {e}")
                        finally:
                            clear_task_context()

                    t = threading.Thread(target=_bg_job, name=f"gen-{task_id}")
                    t.daemon = True
                    t.start()

                    return JsonResponse({
                        'success': True,
                        'api_list': api_list,
                        'file_path': file_path,
                        'file_id': schema_record.id,
                        'task_id': task_id
                    })

                return JsonResponse({
                    'success': True,
                    'api_list': api_list,
                    'file_path': file_path,
                    'file_id': schema_record.id
                })
                
            except Exception as e:
                logger.error(f"文件保存失败: {str(e)}", exc_info=True)
                return JsonResponse({
                    'success': False,
                    'error': f'文件保存失败: {str(e)}'
                })
        
        elif 'generate_test_cases' in request.POST:
            file_path = request.POST.get('file_path')
            file_id = request.POST.get('file_id')
            selected_apis = json.loads(request.POST.get('selected_apis'))
            selected_api_payload = selected_apis
            if isinstance(selected_apis, list) and selected_apis and isinstance(selected_apis[0], dict):
                selected_apis = [item.get('path') for item in selected_apis if item.get('path')]
            count_per_api = int(request.POST.get('count_per_api', 1))
            priority = request.POST.get('priority', 'P0')
            llm_provider = request.POST.get('llm_provider', 'deepseek')
            task_id = request.POST.get('task_id') or f"task_{int(time.time()*1000)}_{request.user.id if request.user.is_authenticated else 'anon'}"
            
            import threading
            def _bg_job():
                try:
                    set_task_context(task_id)
                    rules_override = request.POST.get('rules_override') or None
                    result = generate_test_cases_for_apis(
                        file_path, selected_apis, count_per_api, priority, llm_provider, task_id,
                        rules_override=rules_override
                    )
                    if result and result.get('success'):
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                updated_json = f.read()
                            # 修复历史数据中的乱码占位
                            updated_json = updated_json.replace("??????", "字段类型定义")
                            schema_obj = None
                            if file_id:
                                try:
                                    schema_obj = ApiSchemaFile.objects.get(id=file_id)
                                except ApiSchemaFile.DoesNotExist:
                                    schema_obj = None
                            if not schema_obj:
                                schema_obj = ApiSchemaFile.objects.filter(file_path=file_path).order_by('-id').first()
                            if schema_obj:
                                generation = ApiCaseGeneration.objects.create(
                                    schema_file=schema_obj,
                                    selected_paths=json.dumps(selected_api_payload, ensure_ascii=False),
                                    count_per_api=count_per_api,
                                    priority=priority,
                                    llm_provider=llm_provider,
                                    rules_override=rules_override or '',
                                    task_id=task_id,
                                    generated_cases=result.get('generated_cases', 0),
                                    selected_api_count=result.get('selected_api_count', 0),
                                    result_json=updated_json
                                )
                                try:
                                    from ..agents.progress_registry import set_progress as _set_progress
                                    _set_progress(task_id, {
                                        'generation_id': generation.id
                                    })
                                except Exception:
                                    pass
                        except Exception as e:
                            logger.error(f"生成记录持久化失败: {e}")
                except Exception as e:
                    logger.error(f"后台生成失败: {e}")
                finally:
                    clear_task_context()
            t = threading.Thread(target=_bg_job, name=f"gen-{task_id}")
            t.daemon = True
            t.start()
            
            return JsonResponse({
                'success': True,
                'task_id': task_id
            })
        
        else:
            return JsonResponse({
                'success': False,
                'error': '未能找到文件或生成请求'
            })
    
    return JsonResponse({
        'success': False,
        'error': '不支持的请求方法'
    })


@require_http_methods(["GET"])
def api_schema_files(request):
    """接口定义文件历史列表"""
    items = ApiSchemaFile.objects.all().order_by('-created_at')
    data = [
        {
            'id': item.id,
            'file_name': item.file_name,
            'created_at': item.created_at.isoformat()
        }
        for item in items
    ]
    return JsonResponse({'success': True, 'items': data})


@require_http_methods(["GET"])
def api_schema_file_detail(request, file_id: int):
    """接口定义文件详情（字段+类型）"""
    try:
        item = ApiSchemaFile.objects.get(id=file_id)
    except ApiSchemaFile.DoesNotExist:
        return JsonResponse({'success': False, 'message': '记录不存在'}, status=404)
    return JsonResponse({
        'success': True,
        'item': {
            'id': item.id,
            'file_name': item.file_name,
            'file_path': item.file_path,
            'field_schema': item.field_schema,
            'created_at': item.created_at.isoformat(),
            'updated_at': item.updated_at.isoformat()
        }
    })


@require_http_methods(["GET"])
def api_case_generation_list(request):
    """接口用例生成历史列表"""
    items = ApiCaseGeneration.objects.select_related('schema_file').all().order_by('-created_at')
    data = [
        {
            'id': item.id,
            'file_name': item.schema_file.file_name,
            'generated_cases': item.generated_cases,
            'selected_api_count': item.selected_api_count,
            'task_id': item.task_id,
            'created_at': item.created_at.isoformat()
        }
        for item in items
    ]
    return JsonResponse({'success': True, 'items': data})


@require_http_methods(["GET"])
def api_case_generation_detail(request, generation_id: int):
    """接口用例生成详情"""
    try:
        item = ApiCaseGeneration.objects.select_related('schema_file').get(id=generation_id)
    except ApiCaseGeneration.DoesNotExist:
        return JsonResponse({'success': False, 'message': '记录不存在'}, status=404)
    return JsonResponse({
        'success': True,
        'item': {
            'id': item.id,
            'file_name': item.schema_file.file_name,
            'generated_cases': item.generated_cases,
            'selected_api_count': item.selected_api_count,
            'task_id': item.task_id,
            'result_json': item.result_json,
            'created_at': item.created_at.isoformat()
        }
    })


def get_generation_progress_api(request):
    """获取进度查询，传入task_id 返回内存注册中的进度"""
    try:
        task_id = request.GET.get('task_id')
        if not task_id:
            return JsonResponse({'success': False, 'message': '缺少 task_id'})
        progress = get_task_progress(task_id)
        if not progress:
            return JsonResponse({'success': False, 'message': '未找到进度信息'})
        
        
        progress_dict = progress.dict() if hasattr(progress, 'dict') else progress
        return JsonResponse({'success': True, 'progress': progress_dict})
    except Exception as e:
        logger.error(f"获取进度失败: {e}")
        return JsonResponse({'success': False, 'message': str(e)})


def get_testcase_rule_template(request):
    """返回模板中的“测试用例生成规则”文本"""
    try:
        from ..agents.prompts import PromptTemplateManager
        mgr = PromptTemplateManager()
        cfg = mgr.config.get('api_test_case_generator') or {}
        human_tpl = cfg.get('human_template') or ''
        rule_text = ''
        if human_tpl:
            marker = '## 测试用例生成规则'
            idx = human_tpl.find(marker)
            if idx >= 0:
                rule_text = human_tpl[idx:]
            else:
                rule_text = human_tpl
        return JsonResponse({'success': True, 'rule_text': rule_text})
    except Exception as e:
        logger.error(f"读取模板失败: {e}")
        return JsonResponse({'success': False, 'message': str(e)})
    
    
@require_http_methods(["POST"])
def update_status(request):
    try:
        data = json.loads(request.body)
        test_case_id = data.get('test_case_id')
        status = data.get('status')
        if not test_case_id or not status:
            return JsonResponse({'success': False, 'message': '缺少用例ID或状态'}, status=400)

        test_case = TestCase.objects.get(id=test_case_id)
        test_case.status = status
        test_case.save(update_fields=['status'])
        return JsonResponse({'success': True})
    except TestCase.DoesNotExist:
        return JsonResponse({'success': False, 'message': '未找到测试用例'}, status=404)
    except Exception as e:
        return JsonResponse({'success': False, 'message': str(e)}, status=500)
