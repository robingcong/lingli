from django.db import models
from django.contrib.auth.models import User


class TestCase(models.Model):
    """测试用例模型"""

    STATUS_CHOICES = [
        ('pending', '待评审'),
        ('approved', '评审通过'),
        ('rejected', '评审未通过'),
    ]

    BU_CHOICES = [
        ('education', '教育'),
        ('user_center', '用户中心'),
        ('collaboration', '协同'),
        ('im', 'IM'),
        ('workspace', '工作台'),
        ('recruitment', '招聘'),
        ('work_management', '工作管理'),
        ('ai_application', 'AI 应用'),
        ('operation_platform', '运营平台'),
    ]

    PRIORITY_CHOICES = [
        ('p0', 'P0'),
        ('p1', 'P1'),
        ('p2', 'P2'),
        ('p3', 'P3'),
    ]

    title = models.CharField(max_length=200, verbose_name="测试用例标题")
    description = models.TextField(verbose_name="测试用例描述")
    requirements = models.TextField(verbose_name="需求描述", blank=True)
    code_snippet = models.TextField(verbose_name="代码片段", blank=True)
    test_steps = models.TextField(verbose_name="测试步骤")
    expected_results = models.TextField(verbose_name="预期结果")
    actual_results = models.TextField(verbose_name="实际结果", blank=True)
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name="评审状态"
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='created_testcases',
        verbose_name="创建者",
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    llm_provider = models.CharField(max_length=50, null=True, blank=True)
    bu = models.CharField(max_length=50, choices=BU_CHOICES, blank=True, verbose_name='BU')
    feature = models.CharField(max_length=100, blank=True, verbose_name='Feature')
    priority = models.CharField(max_length=2, choices=PRIORITY_CHOICES, blank=True, verbose_name='Priority')

    def __str__(self):
        return (
            f"用例描述：\n{self.description}\n\n"
            f"测试步骤：\n{self.test_steps}\n\n"
            f"预期结果：\n{self.expected_results}\n"
        )

    class Meta:
        verbose_name = "测试用例"
        verbose_name_plural = "测试用例"


class TestCaseReview(models.Model):
    """测试用例评审记录"""

    test_case = models.ForeignKey(
        TestCase,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name="测试用例"
    )
    reviewer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='reviews',
        verbose_name="评审人"
    )
    review_comments = models.TextField(verbose_name="评审意见")
    review_date = models.DateTimeField(auto_now_add=True, verbose_name="评审时间")

    def __str__(self):
        return f"Review for {self.test_case.title}"

    class Meta:
        verbose_name = "测试用例评审"
        verbose_name_plural = "测试用例评审"


class TestCaseAIReview(models.Model):
    """AI评审结果（与用例一对一关联，覆盖更新）"""

    test_case = models.OneToOneField(
        TestCase,
        on_delete=models.CASCADE,
        related_name='ai_review',
        verbose_name="测试用例"
    )
    provider = models.CharField(max_length=50, blank=True, verbose_name="模型提供商")
    score = models.IntegerField(null=True, blank=True, verbose_name="评分")
    recommendation = models.CharField(max_length=50, blank=True, verbose_name="结论")
    raw_result = models.TextField(verbose_name="原始评审结果")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    def __str__(self):
        return f"AI Review for {self.test_case.title}"

    class Meta:
        verbose_name = "AI评审结果"
        verbose_name_plural = "AI评审结果"


class KnowledgeBase(models.Model):
    """知识库条目"""

    title = models.CharField(max_length=200, verbose_name="知识条目标题")
    content = models.TextField(verbose_name="知识内容")
    vector_id = models.CharField(max_length=100, blank=True, verbose_name="向量ID")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = "知识库"
        verbose_name_plural = "知识库"


class KnowledgeDocument(models.Model):
    """RAG 文档主表。"""

    source_path = models.CharField(max_length=500, unique=True, verbose_name="文档路径")
    title = models.CharField(max_length=255, verbose_name="标题")
    doc_type = models.CharField(max_length=32, blank=True, verbose_name="文档类型")
    content = models.TextField(verbose_name="全文内容")
    content_hash = models.CharField(max_length=64, db_index=True, verbose_name="内容哈希")
    file_mtime = models.FloatField(default=0, verbose_name="文件修改时间")
    chunk_count = models.IntegerField(default=0, verbose_name="Chunk 数量")
    status = models.CharField(max_length=32, default="indexed", verbose_name="同步状态")
    last_indexed_at = models.DateTimeField(null=True, blank=True, verbose_name="最近索引时间")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return self.title

    class Meta:
        db_table = "knowledge_document"
        verbose_name = "知识文档"
        verbose_name_plural = "知识文档"


class KnowledgeChunk(models.Model):
    """RAG chunk 明细表。"""

    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name="所属文档",
    )
    chunk_id = models.CharField(max_length=128, unique=True, verbose_name="Chunk ID")
    chunk_index = models.IntegerField(default=0, verbose_name="Chunk 顺序")
    content = models.TextField(verbose_name="Chunk 内容")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return self.chunk_id

    class Meta:
        db_table = "knowledge_chunk"
        verbose_name = "知识分块"
        verbose_name_plural = "知识分块"


class PRDAnalysis(models.Model):
    """PRD 分析记录"""

    file_name = models.CharField(max_length=255, verbose_name="文件名")
    prd_content = models.TextField(verbose_name="PRD 内容")
    analysis_result = models.TextField(verbose_name="分析结果")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return self.file_name

    class Meta:
        verbose_name = "PRD分析记录"
        verbose_name_plural = "PRD分析记录"


class ApiSchemaFile(models.Model):
    """API定义文件（字段+类型持久化）"""

    file_name = models.CharField(max_length=255, verbose_name="文件名")
    file_path = models.CharField(max_length=500, verbose_name="文件路径")
    raw_json = models.TextField(verbose_name="原始JSON内容")
    field_schema = models.TextField(verbose_name="字段与类型")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return self.file_name

    class Meta:
        verbose_name = "API定义文件"
        verbose_name_plural = "API定义文件"


class ApiCaseGeneration(models.Model):
    """接口用例生成记录"""

    schema_file = models.ForeignKey(
        ApiSchemaFile,
        on_delete=models.CASCADE,
        related_name="generations",
        verbose_name="API定义文件"
    )
    selected_paths = models.TextField(verbose_name="选择的接口路径")
    count_per_api = models.IntegerField(default=1, verbose_name="每接口用例数")
    priority = models.CharField(max_length=10, verbose_name="优先级")
    llm_provider = models.CharField(max_length=50, verbose_name="模型提供商")
    rules_override = models.TextField(blank=True, verbose_name="覆盖规则")
    task_id = models.CharField(max_length=100, blank=True, verbose_name="任务ID")
    generated_cases = models.IntegerField(default=0, verbose_name="生成用例数")
    selected_api_count = models.IntegerField(default=0, verbose_name="接口数")
    result_json = models.TextField(verbose_name="生成结果JSON")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    def __str__(self):
        return f"{self.schema_file.file_name} - {self.created_at}"

    class Meta:
        verbose_name = "接口用例生成记录"
        verbose_name_plural = "接口用例生成记录"


class PlaneWorkItem(models.Model):
    """Plane 工作项缓存表（用于手动刷新后本地落库）。"""

    project_id = models.CharField(max_length=100, db_index=True, verbose_name="项目ID")
    project_name = models.CharField(max_length=255, blank=True, verbose_name="项目名称")
    work_item_id = models.CharField(max_length=100, unique=True, verbose_name="工作项ID")
    work_item_name = models.CharField(max_length=500, blank=True, verbose_name="工作项标题")
    work_item_content = models.TextField(blank=True, verbose_name="工作项内容")
    raw_payload = models.TextField(blank=True, verbose_name="原始JSON")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    def __str__(self):
        return f"{self.project_name} - {self.work_item_name or self.work_item_id}"

    class Meta:
        verbose_name = "Plane工作项"
        verbose_name_plural = "Plane工作项"
