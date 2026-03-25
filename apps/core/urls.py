from django.urls import path
from django.views.decorators.csrf import csrf_exempt

from . import views
from . import api_views
from .views_sse import stream_logs

urlpatterns = [
    path('', views.index, name='index'),
    path('generate/', csrf_exempt(views.generate), name='generate'),
    path('review/', views.review_view, name='review'),
    path('knowledge/', views.knowledge_view, name='knowledge'),
    path('case-review-detail/', views.case_review_detail, name='case_review_detail'),

    path('upload/', csrf_exempt(views.upload_single_file), name='upload_single_file'),
    path('analyser/', csrf_exempt(views.prd_analyser), name='prd_analyser'),
    path('api_case_generate/', csrf_exempt(views.api_case_generate), name='api_case_generate'),
    path('download_file/', views.download_file, name='download_file'),

    path('api/dashboard/', api_views.dashboard, name='api_dashboard'),
    path('api/llm-providers/', api_views.llm_providers, name='api_llm_providers'),
    path('api/test-cases-list/', api_views.test_cases_list, name='api_test_cases_list'),
    path('api/plane-work-items/', csrf_exempt(api_views.plane_work_items), name='api_plane_work_items'),
    path('api/plane-one-click-generate/', csrf_exempt(api_views.plane_one_click_generate), name='api_plane_one_click_generate'),

    path('api/copy-test-cases/', views.copy_test_cases, name='copy_test_cases'),
    path('api/export-test-cases-excel/', views.export_test_cases_excel, name='export_test_cases_excel'),
    path('api/test-case/<int:test_case_id>/', views.get_test_case, name='get_test_case'),
    path('api/test-cases/<str:test_case_ids>/', views.get_test_cases, name='get_test_cases'),
    path('api/update-test-case/', csrf_exempt(views.update_test_case), name='update_test_case'),
    path('api/update-status/', csrf_exempt(views.update_status), name='update_status'),
    path('core/save-test-case/', csrf_exempt(views.save_test_case), name='save_test_case'),
    path('api/review/', csrf_exempt(views.case_review), name='case_review'),
    path('api/add-knowledge/', csrf_exempt(views.add_knowledge), name='add_knowledge'),
    path('api/knowledge-list/', views.knowledge_list, name='knowledge_list'),
    path('api/knowledge-library/', views.knowledge_library_list, name='knowledge_library_list'),
    path('api/knowledge-library/detail/', views.knowledge_library_detail, name='knowledge_library_detail'),
    path('api/search-knowledge/', csrf_exempt(views.search_knowledge), name='search_knowledge'),
    path('api/delete-test-cases/', csrf_exempt(views.delete_test_cases), name='delete_test_cases'),
    path('api/prd-analyses/', views.prd_analysis_list, name='prd_analysis_list'),
    path('api/prd-analyses/<int:analysis_id>/', csrf_exempt(views.prd_analysis_detail), name='prd_analysis_detail'),
    path('api/api-schema-files/', views.api_schema_files, name='api_schema_files'),
    path('api/api-schema-files/<int:file_id>/', views.api_schema_file_detail, name='api_schema_file_detail'),
    path('api/api-case-generations/', views.api_case_generation_list, name='api_case_generation_list'),
    path('api/api-case-generations/<int:generation_id>/', views.api_case_generation_detail, name='api_case_generation_detail'),
    path('api/get-generation-progress/', views.get_generation_progress_api, name='get_generation_progress'),
    path('api/testcase-rule-template/', views.get_testcase_rule_template, name='get_testcase_rule_template'),
    path('api/stream-logs/', stream_logs, name='stream_logs')
]
