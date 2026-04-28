"""sports_management URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from athletic_system import views
from django.conf import settings
from django.conf.urls.static import static
from athletic_system.admin import admin_site

urlpatterns = [
    # 管理后台
    path('admin/', admin_site.urls),
    # 登录页面
    path('', views.login_view, name='login'),
    # 裁判仪表盘
    path('judge/dashboard/', views.judge_dashboard, name='judge_dashboard'),
    # 裁判录入比赛成绩
    path('judge/record/<int:event_id>/', views.record_result, name='record_result'),
    # 运动员仪表盘
    path('athlete/dashboard/', views.athlete_dashboard, name='athlete_dashboard'),
    # 运动员报名参赛
    path('athlete/register/<int:event_id>/', views.register_event, name='register_event'),
    # 运动员退赛
    path('athlete/quit/<int:result_id>/', views.quit_event, name='quit_event'),
    # 退出登录
    path('logout/', views.logout_view, name='logout')
    # 媒体文件服务
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT) 