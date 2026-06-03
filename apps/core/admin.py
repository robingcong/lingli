from django.contrib import admin
from .models import TestCase, TestCaseGenerationJob, TestCaseReview, KnowledgeBase, PlaneWorkItem

@admin.register(TestCase)
class TestCaseAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'created_by', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(TestCaseReview)
class TestCaseReviewAdmin(admin.ModelAdmin):
    list_display = ('test_case', 'reviewer', 'review_date')
    list_filter = ('review_date',)
    search_fields = ('test_case__title', 'review_comments')
    readonly_fields = ('review_date',)

@admin.register(KnowledgeBase)
class KnowledgeBaseAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('title', 'content')
    readonly_fields = ('created_at', 'updated_at') 


@admin.register(PlaneWorkItem)
class PlaneWorkItemAdmin(admin.ModelAdmin):
    list_display = ('project_name', 'work_item_id', 'work_item_name', 'updated_at')
    list_filter = ('project_name', 'updated_at')
    search_fields = ('project_name', 'work_item_id', 'work_item_name', 'work_item_content')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TestCaseGenerationJob)
class TestCaseGenerationJobAdmin(admin.ModelAdmin):
    list_display = ('id', 'source_type', 'source_title', 'status', 'progress', 'llm_provider', 'created_at')
    list_filter = ('source_type', 'status', 'llm_provider', 'created_at')
    search_fields = ('source_title', 'requirements', 'message', 'error_message')
    readonly_fields = ('created_at', 'updated_at', 'started_at', 'finished_at')
