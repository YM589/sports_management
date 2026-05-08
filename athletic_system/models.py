from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.utils import timezone
import datetime

class User(AbstractUser):
    ROLE_CHOICES = (
        ('admin', '管理员'),
        ('judge', '裁判员'),
        ('athlete', '运动员'),
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='admin', verbose_name='角色')
    phone = models.CharField(
        max_length=11,
        blank=True,
        validators=[RegexValidator(
            regex=r'^1[3-9]\d{9}$',
            message='请输入有效的手机号码'
        )]
    )
    
    groups = models.ManyToManyField(
        'auth.Group',
        verbose_name='groups',
        blank=True,
        help_text='The groups this user belongs to.',
        related_name='athletic_users',
        related_query_name='athletic_user'
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        verbose_name='user permissions',
        blank=True,
        help_text='Specific permissions for this user.',
        related_name='athletic_users',
        related_query_name='athletic_user'
    )
    
    class Meta:
        verbose_name = '用户'
        verbose_name_plural = '用户'

class Judge(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': 'judge'}, related_name='judge_profile')
    title = models.CharField(max_length=50, verbose_name='职称')
    specialty = models.CharField(max_length=100, verbose_name='专长项目')
    # experience_years = models.IntegerField(verbose_name='从业年限', validators=[MinValueValidator(0)], default=0)
    is_available = models.BooleanField(default=True, verbose_name='是否可排班')
    
    def get_upcoming_events(self):
        return self.user.judging_events.filter(date__gte=timezone.now()).order_by('date')
        
    def get_judged_events_count(self):
        return self.user.judging_events.filter(status='finished').count()
    
    class Meta:
        verbose_name = '裁判员'
        verbose_name_plural = '裁判员'
        
    def __str__(self):
        return self.user.username

class Athlete(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': 'athlete'}, related_name='athlete_profile')
    student_id = models.CharField(max_length=20, verbose_name='学号', unique=True)
    team = models.ForeignKey('Team', on_delete=models.SET_NULL, null=True, verbose_name='所属团队', related_name='athletes')
    age = models.IntegerField(
        verbose_name='年龄',
        validators=[MinValueValidator(16), MaxValueValidator(30)]
    )
    gender = models.CharField(max_length=10, choices=(
        ('male', '男'),
        ('female', '女'),
    ), verbose_name='性别', db_index=True)
    # height = models.FloatField(verbose_name='身高(cm)', validators=[MinValueValidator(100), MaxValueValidator(250)], null=True, blank=True)
    # weight = models.FloatField(verbose_name='体重(kg)', validators=[MinValueValidator(30), MaxValueValidator(150)], null=True, blank=True)
    is_active = models.BooleanField(default=True, verbose_name='是否在籍')
    
    def get_competition_history(self):
        return self.user.results.select_related('event').order_by('-event__date')
        
    def get_medals_count(self):
        return self.user.results.filter(rank__lte=3).count()
        
    def get_upcoming_events(self):
        return Event.objects.filter(
            id__in=self.user.results.filter(event__date__gte=timezone.now()).values_list('event_id', flat=True)
        ).order_by('date')
    
    class Meta:
        verbose_name = '运动员'
        verbose_name_plural = '运动员'
        
    def __str__(self):
        return self.user.username

class Event(models.Model):
    name = models.CharField(max_length=100, verbose_name='项目名称')
    date = models.DateTimeField(verbose_name='比赛时间')
    duration = models.DurationField(verbose_name='比赛持续时间', default=datetime.timedelta(hours=2))
    location = models.CharField(max_length=100, verbose_name='比赛地点')
    status = models.CharField(max_length=20, choices=(
        ('pending', '未开始'),
        ('ongoing', '进行中'),
        ('finished', '已结束'),
    ), default='pending', verbose_name='比赛状态')
    judges = models.ManyToManyField(User, related_name='judging_events', limit_choices_to={'role': 'judge'})
    description = models.TextField(verbose_name='项目描述', blank=True)
    max_participants = models.IntegerField(verbose_name='最大参赛人数', default=0)
    registration_deadline = models.DateTimeField(verbose_name='报名截止时间', null=True, blank=True)
    
    def update_status(self):
        now = datetime.datetime.now()  # 朴素时间（无时区）
        end_time = self.date + self.duration

        # 移除微秒，保持精度一致
        now = now.replace(microsecond=0)
        end_time = end_time.replace(microsecond=0)
        
        if now < self.date:
            new_status = 'pending'
        elif now > end_time:
            new_status = 'finished'
        else:
            new_status = 'ongoing'
            
        if new_status != self.status:
            self.status = new_status
            self.save(update_fields=['status'])
    
    def save(self, *args, **kwargs):
        self.update_status()
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = '比赛项目'
        verbose_name_plural = '比赛项目'
        ordering = ['date']  # 按日期排序

    def __str__(self):
        return self.name

class Result(models.Model):
    athlete = models.ForeignKey(User, on_delete=models.CASCADE, related_name='results', limit_choices_to={'role': 'athlete'}, verbose_name='运动员')
    event = models.ForeignKey(Event, on_delete=models.CASCADE, verbose_name='比赛项目')
    score = models.FloatField(null=True, blank=True, verbose_name='成绩')
    rank = models.IntegerField(null=True, blank=True, verbose_name='排名')
    is_quit = models.BooleanField(default=False, verbose_name='是否弃权')
    quit_reason = models.TextField(blank=True, verbose_name='弃权原因')
    confirmed = models.BooleanField(default=False, verbose_name='成绩是否确认')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='提交时间')
    
    class Meta:
        verbose_name = '比赛成绩'
        verbose_name_plural = '比赛成绩'
        
    def __str__(self):
        status = '已弃权' if self.is_quit else (f'{self.score}' if self.score is not None else '未记录')
        return f'{self.athlete.username} - {self.event.name}: {status}'

class Team(models.Model):
    name = models.CharField(max_length=100, verbose_name='团队名称')
    score = models.IntegerField(default=0, verbose_name='团队总分')
    
    class Meta:
        verbose_name = '团队'
        verbose_name_plural = '团队'

    def __str__(self):
        return self.name

class Announcement(models.Model):
    title = models.CharField(max_length=200, verbose_name='标题')
    content = models.TextField(verbose_name='内容')
    publish_time = models.DateTimeField(auto_now_add=True, verbose_name='发布时间')
    is_active = models.BooleanField(default=True, verbose_name='是否激活')
    priority = models.IntegerField(default=0, verbose_name='优先级', help_text='数字越大优先级越高')
    
    class Meta:
        verbose_name = '公告'
        verbose_name_plural = '公告'
        ordering = ['-priority', '-publish_time']
        
    def __str__(self):
        return self.title
