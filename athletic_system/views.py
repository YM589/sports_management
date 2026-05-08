from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import *
from django.http import JsonResponse
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth import logout
from django.utils import timezone
from django.db.models import F, Count, Avg
from django.core.cache import cache
from django.views.decorators.http import require_http_methods
from django.db import transaction
import logging

logger = logging.getLogger(__name__)

@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == 'POST':
        try:
            username = request.POST.get('username')
            password = request.POST.get('password')
            role = request.POST.get('role')
            
            if not all([username, password, role]):
                raise ValidationError('请填写所有必填字段')
            
            user = authenticate(username=username, password=password)
            if user is not None:
                if user.role == role:
                    login(request, user)
                    logger.info(f'用户 {username} 以 {role} 角色成功登录')
                    if role == 'admin':
                        return redirect('/admin/')
                    elif role == 'judge':
                        return redirect('judge_dashboard')
                    else:
                        return redirect('athlete_dashboard')
                else:
                    raise ValidationError('角色不匹配')
            else:
                raise ValidationError('用户名或密码错误')
                
        except ValidationError as e:
            messages.error(request, str(e))
            logger.warning(f'登录失败: {str(e)}')
        except Exception as e:
            messages.error(request, '系统错误，请稍后重试')
            logger.error(f'登录异常: {str(e)}')
    
    if request.user.is_authenticated:
        if request.user.role == 'admin':
            return redirect('/admin/')
        elif request.user.role == 'judge':
            return redirect('judge_dashboard')
        else:
            return redirect('athlete_dashboard')
    
    return render(request, 'athletic_system/login.html')

@login_required
def judge_dashboard(request):
    if request.user.role != 'judge':
        raise PermissionDenied
    
    # 使用缓存获取裁判的比赛数据
    cache_key = f'judge_events_{request.user.id}'
    events = cache.get(cache_key)
    
    if events is None:
        events = Event.objects.filter(judges=request.user).select_related()
        
        # 为每个事件预处理统计数据
        for event in events:
            event.total_participants = event.result_set.count()
            event.confirmed_count = event.result_set.filter(confirmed=True).count()
            event.quit_count = event.result_set.filter(is_quit=True).count()
            best_result = event.result_set.filter(confirmed=True).order_by('-score').first()
            event.best_score = best_result.score if best_result else None
        
        # 设置缓存，有效期30分钟
        # cache.set(cache_key, events, 1800)
        # 设置缓存，有效期1分钟
        cache.set(cache_key, events, 60)
    
    # 获取所有激活状态的公告
    announcements = Announcement.objects.filter(is_active=True).order_by('-publish_time')

    return render(request, 'athletic_system/judge_dashboard.html', {
        'events': events,
        'judge': Judge.objects.get(user=request.user),
        'announcements': announcements
    })

@login_required
def record_result(request, event_id):
    if request.user.role != 'judge':
        raise PermissionDenied
    
    event = get_object_or_404(Event, id=event_id)
    if request.user not in event.judges.all():
        raise PermissionDenied
    
    if request.method == 'POST':
        try:
            athlete_id = request.POST.get('athlete_id')
            # print(athlete_id)
            score = request.POST.get('score')
            # print(score)
            
            if not athlete_id or not score:
                return JsonResponse({'status': 'error', 'message': '缺少必要参数'}, status=400)
            
            # 验证运动员ID是否为有效的用户ID
            try:
                athlete_id = int(athlete_id)  # 显式转换为整数
                athlete = User.objects.get(id=athlete_id)
            except (User.DoesNotExist, ValueError):
                return JsonResponse({'status': 'error', 'message': '无效的运动员ID'}, status=400)
            
            # 改进的分数处理逻辑
            try:
                # 先尝试将输入转换为浮点数
                score_value = float(score)
                # 确保分数是正数
                if score_value < 0:
                    raise ValueError("分数不能为负数")
            except ValueError as ve:
                return JsonResponse({'status': 'error', 'message': '成绩格式不正确，请输入有效的正数'}, status=400)
            
            with transaction.atomic():
                result = Result.objects.select_for_update().get(
                    event_id=event_id,
                    athlete_id=athlete_id,  # 使用整数ID查询
                    is_quit=False,
                    confirmed=False
                )
                
                result.score = score_value
                result.confirmed = True
                result.save()
                
                # 更新排名
                update_rankings(event)
                # 更新团队分数
                update_team_scores()
                
                # 清除相关缓存
                cache.delete(f'judge_events_{request.user.id}')
                cache.delete(f'athlete_dashboard_{athlete_id}')
            
            logger.info(f'裁判 {request.user.username} 为运动员 {athlete.username}（ID:{athlete_id}）在项目 {event.name} 中记录成绩 {score_value}')
            return JsonResponse({'status': 'success'})
            
        except Result.DoesNotExist:
            return JsonResponse({'status': 'error', 'message': '找不到对应的比赛记录'}, status=404)
        except ValueError as ve:
            return JsonResponse({'status': 'error', 'message': str(ve)}, status=400)
        except Exception as e:
            logger.error(f'记录成绩时发生错误: {str(e)}')
            return JsonResponse({'status': 'error', 'message': '服务器内部错误，请稍后再试'}, status=500)
    
    results = Result.objects.filter(event=event).select_related('athlete')
    # result = Result.objects.filter(event=event).select_related('athlete').first()
    # print(result.athlete.id) 
    return render(request, 'athletic_system/record_result.html', {
        'event': event,
        'results': results
    })

@login_required
def athlete_dashboard(request):
    athlete = Athlete.objects.get(user=request.user)
    results = Result.objects.filter(athlete=request.user)
    team_ranking = Team.objects.all().order_by('-score')

    # 获取可报名的比赛项目
    available_events = []
    for event in Event.objects.filter(status='pending', registration_deadline__gt=timezone.now()):
        registered_count = Result.objects.filter(event=event).count()
        # 检查该运动员是否已经报名了此比赛项目
        is_registered = Result.objects.filter(event=event, athlete=athlete.user).exists()
        if event.max_participants > registered_count and not is_registered:
            available_events.append(event)

    # 获取所有激活状态的公告
    announcements = Announcement.objects.filter(is_active=True).order_by('-publish_time')

    context = {
        'athlete': athlete,
        'results': results,
        'team_ranking': team_ranking,
        'available_events': available_events,
        'announcements': announcements
    }
    return render(request, 'athletic_system/athlete_dashboard.html', context)

@login_required
def register_event(request, event_id):
    try:
        with transaction.atomic():
            athlete = get_object_or_404(Athlete, user=request.user)
            event = get_object_or_404(Event, id=event_id)

            # 验证比赛是否可以报名
            if event.status != 'pending':
                messages.error(request, '该比赛已经开始或已结束，无法报名')
                return redirect('athlete_dashboard')

            if event.registration_deadline and event.registration_deadline < timezone.now():
                messages.error(request, '报名已截止')
                return redirect('athlete_dashboard')

            # 检查是否还有剩余名额
            registered_count = Result.objects.filter(event=event).count()
            if registered_count >= event.max_participants:
                messages.error(request, '该比赛名额已满')
                return redirect('athlete_dashboard')

            # 检查该运动员是否已经报名了此比赛项目
            if Result.objects.filter(event=event, athlete=athlete.user).exists():
                messages.error(request, '您已报名该比赛')
                return redirect('athlete_dashboard')

            Result.objects.create(
                athlete=athlete.user,
                event=event
            )
            messages.success(request, '报名成功')
            logger.info(f'运动员 {athlete.user.username} 成功报名比赛 {event.name}')

    except Exception as e:
        logger.error(f'报名比赛时发生错误: {str(e)}')
        messages.error(request, '报名失败，请稍后重试')

    return redirect('athlete_dashboard')

@login_required
def quit_event(request, result_id):
    if request.user.role != 'athlete':
        raise PermissionDenied
    
    try:
        with transaction.atomic():
            result = get_object_or_404(Result, id=result_id, athlete=request.user)
            if result.confirmed:
                messages.error(request, '成绩已确认，无法弃权')
                return redirect('athlete_dashboard')
            
            if result.event.status != 'pending':
                messages.error(request, '比赛已开始或已结束，无法弃权')
                return redirect('athlete_dashboard')
            
            result.is_quit = True
            result.quit_reason = request.POST.get('quit_reason', '')
            result.save()
            
            logger.info(f'运动员 {request.user.username} 已弃权比赛 {result.event.name}')
            messages.success(request, '已成功弃权')
            
    except Exception as e:
        logger.error(f'处理弃权请求时发生错误: {str(e)}')
        messages.error(request, '处理弃权请求失败，请稍后重试')
    
    return redirect('athlete_dashboard')

def update_rankings(event):
    """更新某个项目的排名"""
    results = Result.objects.filter(
        event=event,
        is_quit=False,
        confirmed=True
    ).order_by('-score')
    
    for i, result in enumerate(results, 1):
        result.rank = i
        result.save()

def update_team_scores():
    """更新团队总分"""
    teams = Team.objects.all()
    for team in teams:
        score = 0
        results = Result.objects.filter(
            athlete__athlete_profile__team=team,  # 明确使用 related_name
            confirmed=True,
            is_quit=False,
            rank__isnull=False
        ).select_related(
            'athlete__athlete_profile__team'  # 预加载关联对象，减少数据库查询
        )
        
        # 计算得分（例如：第一名5分，第二名3分，第三名1分）
        for result in results:
            if result.rank == 1:
                score += 5
            elif result.rank == 2:
                score += 3
            elif result.rank == 3:
                score += 1
        
        team.score = score
        team.save()

def logout_view(request):
    logout(request)
    return redirect('login')
