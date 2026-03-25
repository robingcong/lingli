from pathlib import Path
import yaml
import json
import re
from typing import Dict, Any, List, Optional
from langchain.prompts import ChatPromptTemplate
from langchain.prompts.chat import SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.messages import HumanMessage

from apps.knowledge.schemas import RAGContextResult

class PromptTemplateManager:
    """提示词模板管理器"""
    
    def __init__(self):
        """初始化，加载配置文件"""
        config_path = Path(__file__).parent / "prompts_config.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def get_test_case_generator_prompt(self) -> ChatPromptTemplate:
        """获取测试用例生成的提示词模板"""
        config = self.config['test_case_generator']
        
        # 准备系统消息的变量并格式化模板
        system_vars = {
            'role': config['role'],
            'capabilities': config['capabilities'],
            'test_methods': ', '.join(config['test_methods']),
            'test_types': ', '.join(config['test_types'])
        }
        
        # 创建系统消息模板
        system_message_prompt = SystemMessagePromptTemplate.from_template(
            config['system_template'].format(**system_vars)  # 直接格式化模板
        )
        
        # 创建人类消息模板
        human_message_prompt = HumanMessagePromptTemplate.from_template(
            config['human_template']
        )
        
        # 组合成聊天提示词模板
        return ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt
        ])

    def get_test_case_reviewer_prompt(self) -> ChatPromptTemplate:
        """获取测试用例评审的提示词模板"""
        config = self.config['test_case_reviewer']
        
        # 准备系统消息的变量并格式化模板
        system_vars = {
            'role': config['role'],
            'evaluation_aspects': ', '.join(config['evaluation_aspects'])
        }
        
        # 创建系统消息模板
        system_message_prompt = SystemMessagePromptTemplate.from_template(
            config['system_template'].format(**system_vars)  # 直接格式化模板
        )
        
        # 准备人类消息的变量
        human_vars = {
            'review_points': '\n'.join(f"- {point}" for point in config['review_points'])
        }
        
        # 创建人类消息模板 - 不要在这里格式化 test_case
        human_message_prompt = HumanMessagePromptTemplate.from_template(
            config['human_template']
        )
        
        # 组合成聊天提示词模板
        return ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt
        ])
        
    def get_prd_analyser_prompt(self) -> ChatPromptTemplate:
        """获取PRD分析的提示词模板"""
        config = self.config['prd_analyser']
        
        # 准备系统消息的变量并格式化模板
        system_vars = {
            'role': config['role'],
            'capabilities': config['capabilities'],
            'analysis_focus': ', '.join(config['analysis_focus'])
        }
        
        # 创建系统消息模板
        system_message_prompt = SystemMessagePromptTemplate.from_template(
            config['system_template'].format(**system_vars)  # 直接格式化模板
        )
        
        # 创建人类消息模板
        human_message_prompt = HumanMessagePromptTemplate.from_template(
            config['human_template']
        )
        
        # 组合成聊天提示词模板
        return ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt
        ])
    
    def get_api_test_case_generator_prompt(self) -> ChatPromptTemplate:
        """获取API测试用例生成的提示词模板"""
        config = self.config['api_test_case_generator']
        
        # 准备系统消息的变量并格式化模板
        system_vars = {
            'role': config['role'],
            'capabilities': config['capabilities'],
            'api_analysis_focus': ', '.join(config['api_analysis_focus']),
            'template_understanding': '\n'.join(config['template_understanding']),
            'case_count': '{case_count}'
        }
        
        # 创建系统消息模板
        system_message_prompt = SystemMessagePromptTemplate.from_template(
            config['system_template'].format(**system_vars)  # 直接格式化模板
        )
        
        # 创建人类消息模板
        human_message_prompt = HumanMessagePromptTemplate.from_template(
            config['human_template']
        )
        
        # 组合成聊天提示词模板
        return ChatPromptTemplate.from_messages([
            system_message_prompt,
            human_message_prompt
        ])

class TestCaseGeneratorPrompt:
    """测试用例生成提示词"""
    
    def __init__(self):
        self.prompt_manager = PromptTemplateManager()
        self.prompt_template = self.prompt_manager.get_test_case_generator_prompt()

    def _looks_like_system_function_content(self, requirements: str) -> bool:
        text = (requirements or "").strip()
        if not text:
            return False
        markers = [
            "功能",
            "页面",
            "按钮",
            "菜单",
            "模块",
            "列表",
            "详情",
            "弹窗",
            "表单",
            "提交",
            "保存",
            "编辑",
            "删除",
            "创建",
            "查询",
            "筛选",
            "切换",
            "状态",
            "提示",
            "支持",
            "进入",
            "点击",
            "配置",
            "上传",
            "下载",
            "调度",
        ]
        marker_hits = sum(1 for marker in markers if marker in text)
        numbered_steps = bool(re.search(r"(\d+[.、]|步骤|主要功能|功能点)", text))
        line_count = len([line for line in text.splitlines() if line.strip()])
        return marker_hits >= 3 or numbered_steps or line_count >= 4
    
    def format_messages(
        self,
        requirements: str,
        case_design_methods: str = "",
        case_categories: str = "",
        knowledge_context: str | RAGContextResult = "",
        case_count: int = 10,
        missing_coverage_tags: Optional[List[str]] = None,
        existing_case_summaries: Optional[List[str]] = None,
        retry_round: int = 0,
    ) -> list:
        """格式化消息
        
        Args:
            requirements: 需求描述
            case_design_methods: 测试用例设计方法
            case_categories: 测试用例类型
            knowledge_context: 知识库上下文
            case_count: 生成用例条数
        Returns:
            格式化后的消息列表
        """
        # 处理空值情况
        if not case_design_methods:
            case_design_methods = "所有适用的测试用例设计方法"
        
        if not case_categories:
            case_categories = "所有适用的测试类型"
            
        knowledge_prompt = self._format_knowledge_prompt(knowledge_context)
        quantity_instruction = (
            "，数量不设上限，请尽可能多生成 case，并持续补齐所有覆盖维度"
            if case_count <= 0
            else f"（至少参考目标 {case_count} 条；如果覆盖维度不足应继续补充，优先生成更多 case 以补齐场景覆盖）"
        )
        
        messages = self.prompt_template.format_messages(
            requirements=requirements,
            case_design_methods=case_design_methods,
            case_categories=case_categories,
            case_count=case_count,
            quantity_instruction=quantity_instruction,
            knowledge_context=knowledge_prompt
        )
        if missing_coverage_tags or existing_case_summaries or retry_round:
            supplement_lines = [
                f"补齐要求：当前是第 {retry_round + 1} 轮生成，请避免重复已有测试点。"
            ]
            if existing_case_summaries:
                supplement_lines.append("已有高质量用例摘要：")
                supplement_lines.extend(f"- {item}" for item in existing_case_summaries[:8])
            if missing_coverage_tags:
                supplement_lines.append("当前缺失覆盖维度：")
                supplement_lines.extend(f"- {item}" for item in missing_coverage_tags)
            supplement_lines.append("请优先补齐缺失覆盖维度，输出新的、不重复的高质量 case。")
            messages.append(HumanMessage(content="\n".join(supplement_lines)))
        if self._looks_like_system_function_content(requirements):
            messages.append(
                HumanMessage(
                    content="\n".join(
                        [
                            "当前输入更像系统功能说明/页面操作说明，请按以下方式增强生成质量：",
                            "1. 先识别并覆盖输入中的每个功能子点、按钮动作、页面入口、角色、前置条件和状态变化。",
                            "2. 每个功能子点都要补齐成功路径、失败路径、边界条件、非法输入、权限差异、状态切换、刷新回显、联动校验。",
                            "3. 对按钮、弹窗、表单、列表、详情、上传下载、调度、启停、切换、创建编辑删除等交互，必须写出贴近真实系统操作的步骤。",
                            "4. 预期结果必须写清提示信息方向、页面表现、数据变化、状态变化、上下游联动和可观察结果。",
                            "5. 禁止输出空泛描述，例如“验证功能正常”“验证页面显示正确”；description 必须明确到具体功能点。",
                        ]
                    )
                )
            )
        return messages

    def _format_knowledge_prompt(self, knowledge_context: str | RAGContextResult) -> str:
        if isinstance(knowledge_context, RAGContextResult):
            if not knowledge_context.context_text:
                return "根据你的专业知识"
            return "\n".join(
                [
                    "以下是与当前需求相关的知识库证据，请优先参考高相关证据进行测试设计：",
                    "若知识库证据与用户需求冲突，以用户需求为准。",
                    "若知识库证据不足，不要编造知识库中不存在的规则，可补充通用测试专业知识。",
                    "请重点吸收证据中的业务术语、状态流转、校验规则、边界条件和异常处理。",
                    "",
                    knowledge_context.context_text,
                ]
            )

        if knowledge_context:
            return f"参考以下知识库内容：\n{knowledge_context}"
        return "根据你的专业知识"

class TestCaseReviewerPrompt:
    """测试用例评审提示词"""
    
    def __init__(self):
        self.prompt_manager = PromptTemplateManager()
        self.prompt_template = self.prompt_manager.get_test_case_reviewer_prompt()
    
    def format_messages(self, test_case: Dict[str, Any]) -> list:
        """格式化消息
        
        Args:
            test_case: 测试用例数据
            
        Returns:
            格式化后的消息列表
        """
        # 格式化测试用例数据为字符串
        test_case_str = (
            f"测试用例描述：\n{test_case.get('description', '')}\n\n"
            f"测试步骤：\n{test_case.get('test_steps', '')}\n\n"
            f"预期结果：\n{test_case.get('expected_results', '')}"
        )
        
        # 获取评审点列表
        review_points = '\n'.join(
            f"- {point}" 
            for point in self.prompt_manager.config['test_case_reviewer']['review_points']
        )
        
        return self.prompt_template.format_messages(
            test_case=test_case_str,
            review_points=review_points
        )

    def format_batch_messages(self, test_cases: List[Dict[str, Any]]) -> list:
        """格式化批量评审消息。"""
        review_points = '\n'.join(
            f"- {point}"
            for point in self.prompt_manager.config['test_case_reviewer']['review_points']
        )
        cases_payload = []
        for index, test_case in enumerate(test_cases, start=1):
            cases_payload.append(
                {
                    "index": index,
                    "description": test_case.get("description", ""),
                    "test_steps": test_case.get("test_steps", []),
                    "expected_results": test_case.get("expected_results", []),
                }
            )

        batch_case_str = json.dumps(cases_payload, ensure_ascii=False, indent=2)
        messages = self.prompt_template.format_messages(
            test_case=batch_case_str,
            review_points=review_points,
        )
        messages.append(
            HumanMessage(
                content="\n".join(
                    [
                        "请一次性评审上面所有测试用例，并按输入顺序返回等长 JSON 数组。",
                        "数组中的每个元素对应一个测试用例，必须包含字段：score、strengths、weaknesses、suggestions、missing_scenarios、recommendation、comments。",
                        "禁止输出 JSON 数组之外的任何解释性文本。",
                    ]
                )
            )
        )
        return messages

class PrdAnalyserPrompt:
    """PRD分析提示词"""
    
    def __init__(self):
        self.prompt_manager = PromptTemplateManager()
        self.prompt_template = self.prompt_manager.get_prd_analyser_prompt()
    
    def format_messages(self, markdown_content: str) -> list:
        """格式化消息
        
        Args:
            markdown_content: Markdown格式的PRD文档内容
            
        Returns:
            格式化后的消息列表
        """
        return self.prompt_template.format_messages(
            markdown_content=markdown_content
        )


class APITestCaseGeneratorPrompt:
    """API测试用例生成提示词"""
    
    def __init__(self):
        self.prompt_manager = PromptTemplateManager()
        self.prompt_template = self.prompt_manager.get_api_test_case_generator_prompt()
    
    def format_messages(self, api_info: Dict[str, Any], priority: str, 
                       case_count: int, api_test_case_min_template: str, 
                       include_format_instructions: bool = False,
                       case_rule_override: str | None = None) -> list:
        """格式化消息
        
        Args:
            api_info: API接口信息
            priority: 测试用例优先级
            case_count: 生成测试用例数量
            test_case_template: 测试用例结构模板
            include_format_instructions: 是否包含格式说明（用于重试）
            case_rule_override: 自定义测试用例生成规则（Markdown格式），用于覆盖模板中的默认规则（可选）
            
        Returns:
            格式化后的消息列表
        """
        # 生成响应摘要，如果有内容则包含标题，否则为空
        response_summary = self._format_response_summary(api_info)
        response_block = f"## 响应摘要\n{response_summary}" if response_summary else ""
        
        # 获取基础消息
        messages = self.prompt_template.format_messages(
            api_name=api_info.get('name', ''),
            method=api_info.get('method', ''),
            path=api_info.get('path', ''),
            priority=priority,
            case_count=case_count,
            api_parameters_info=self._format_api_parameters_info(api_info),
            api_response_summary=response_block,
            api_test_case_min_template=api_test_case_min_template
        )

        # 若提供了规则覆盖，将其追加/替换到最后的人类消息中
        if case_rule_override:
            override_text = str(case_rule_override)
            marker = '## 测试用例生成规则'
            for msg in reversed(messages):
                if hasattr(msg, 'content'):
                    content = msg.content
                    idx = content.find(marker)
                    if idx >= 0:
                        msg.content = content[:idx] + override_text
                    else:
                        msg.content += f"\n\n{override_text}"
                    break
        
        # 如果需要格式说明（重试时），追加到最后一个 HumanMessage
        if include_format_instructions:
            from .parsers.api_test_case_parser import get_format_instructions
            format_instr = get_format_instructions()
            format_extra = (
                f"\n\n重要要求：\n"
                f"- 只输出 JSON，不要任何解释性文本\n"
                f"- 严格返回长度为{case_count}的JSON数组\n"
                f"- 数组每个对象必须满足模板字段要求\n"
                f"- 若失败请直接重写为合法JSON\n"
                f"- 严格遵守以下格式说明：\n{format_instr}"
            )
            
            # 找到最后一个 HumanMessage 并追加格式说明
            for msg in reversed(messages):
                if hasattr(msg, 'content') and hasattr(msg, 'type') and msg.type == 'human':
                    msg.content += format_extra
                    break
                elif hasattr(msg, 'content') and hasattr(msg, 'role') and msg.role == 'user':
                    msg.content += format_extra
                    break
        
        return messages
    
    def _format_api_parameters_info(self, api_info: Dict[str, Any]) -> str:
        """格式化参数的关键信息"""
        request = api_info.get('request', {})
        
        # 提取参数信息
        params_info = []
        
        # 从 query 参数
        for param in request.get('query', []):
            params_info.append({
                'name': param.get('key'),
                'type': param.get('paramType'),
                'required': param.get('required'),
                'sample': param.get('value'),
                'minimum': param.get('minimum', None),
                'maximum': param.get('maximum', None),
                'minLength': param.get('minLength', None),
                'maxLength': param.get('maxLength'),
                'location': 'query'
            })
        
        # 从 rest 参数
        for param in request.get('rest', []):
            params_info.append({
                'name': param.get('key'),
                'type': param.get('paramType'),
                'required': param.get('required'),
                'sample': param.get('value'),
                'minimum': param.get('minimum', None),
                'maximum': param.get('maximum', None),
                'minLength': param.get('minLength', None),
                'maxLength': param.get('maxLength', None),
                'location': 'path'
            })
        
        # 从 body 参数
        body = request.get('body', {})
        if body.get('bodyType') == 'JSON':
            json_body = body.get('jsonBody', {})
            schema = json_body.get('jsonSchema', {})
            properties = schema.get('properties', {})
            
            # 解析 jsonValue 字符串为字典
            json_value_dict = {}
            json_value_str = json_body.get('jsonValue', '')
            if json_value_str:
                try:
                    json_value_dict = json.loads(json_value_str)
                except json.JSONDecodeError:
                    pass  # 如果解析失败，使用空字典
            
            # 遍历 jsonValue 中的参数（参数个数和样本值来源）
            for prop_name, sample_value in json_value_dict.items():
                # 从 jsonSchema.properties 中获取类型信息
                prop_info = properties.get(prop_name, {})
                
                params_info.append({
                    'name': prop_name,
                    'type': prop_info.get('type'),
                    'required': prop_info.get('required'),
                    'sample': sample_value,
                    'minimum': prop_info.get('minimum'),
                    'maximum': prop_info.get('maximum'),
                    'minLength': prop_info.get('minLength'),
                    'maxLength': prop_info.get('maxLength'),
                    'location': 'body'
                })
        
        result = ""
        if params_info:
            result += "\n"
            for param in params_info:
                if param['name']:  # 过滤空参数名
                    result += f"- {param['name']} ({param['location']}): {param['type']}"
                    if param['required']:
                        result += " [必填]"
                    if param['sample']:
                        result += f" 样例: {param['sample']}"
                    if param['minimum'] is not None or param['maximum'] is not None:
                        result += f" 范围: {param['minimum']}-{param['maximum']}"
                    if param['minLength'] is not None or param['maxLength'] is not None:
                        result += f" 长度: {param['minLength']}-{param['maxLength']}"
                    result += "\n"
        else:
            result += "无参数\n"
        
        return result
    
    def _format_response_summary(self, api_info: Dict[str, Any]) -> str:
        """格式化响应摘要信息"""
        #TODO: 目前暂不将接口响应信息传入大模型, 后面有需要再补充
        return ""
        response = api_info.get('response', [])
        
        if not response:
            return "响应: 无响应信息"
        
        # 只提取关键信息
        result = "响应摘要:\n"
        for resp in response:
            status_code = resp.get('statusCode', '')
            default_flag = resp.get('defaultFlag', False)
            result += f"- 状态码: {status_code} {'(默认)' if default_flag else ''}\n"
            
            # 只提取响应体的关键字段信息
            body = resp.get('body', {})
            if body.get('bodyType') == 'JSON':
                json_body = body.get('jsonBody', {})
                if json_body.get('jsonValue'):
                    # 只显示关键字段
                    json_value = json_body['jsonValue']
                    if isinstance(json_value, dict):
                        key_fields = ['code', 'message', 'data', 'success']
                        for field in key_fields:
                            if field in json_value:
                                result += f"  {field}: {json_value[field]}\n"
                elif json_body.get('jsonSchema'):
                    # 只显示必填字段
                    required_fields = json_body.get('jsonSchema', {}).get('required', [])
                    if required_fields:
                        result += f"  必填字段: {', '.join(required_fields)}\n"
        
        return result
# 使用示例
if __name__ == "__main__":
    # 测试用例生成
    # generator = TestCaseGeneratorPrompt()
    # messages = generator.format_messages(
    #     requirements="实现用户登录功能",
    #     case_design_methods="等价类划分法",
    #     case_categories="功能测试",
    #     knowledge_context="用户登录需要验证用户名和密码"
    # )
    # print("Generator Messages:", messages)
    
    # # 测试用例评审
    # reviewer = TestCaseReviewerPrompt()
    # test_case = {
    #     "description": "测试用户登录功能",
    #     "test_steps": ["1. 输入用户名", "2. 输入密码", "3. 点击登录按钮"],
    #     "expected_results": ["1. 显示输入框", "2. 密码显示为星号", "3. 登录成功"]
    # }
    # messages = reviewer.format_messages(test_case)
    # print("\nReviewer Messages:", messages)
    
    # PRD分析
    analyser = PrdAnalyserPrompt()
    prd_content = """
    # 用户登录功能
    
    ## 功能描述
    允许用户通过用户名和密码登录系统。
    
    ## 详细需求
    1. 用户需要输入用户名和密码
    2. 系统验证用户名和密码的正确性
    3. 登录成功后跳转到首页
    """
    messages = analyser.format_messages(prd_content)
    print("\nPRD Analyser Messages:", messages)
