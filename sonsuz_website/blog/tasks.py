import json
from collections import OrderedDict

from django.contrib.auth import get_user_model
from django.db.models import F
from django_redis import get_redis_connection
from sonsuz_website.blog.models import Article, Like
from sonsuz_website.blog.api.serializers import CommentSerializer
from config import celery_app

User = get_user_model()

con = get_redis_connection()


@celery_app.task()
def commit_visited():
    visited_list = con.hgetall('blog:visited:list')
    # print(visited_list)
    data = OrderedDict(visited_list)
    for key, value in data.items():
        key = str(key, encoding="utf8")
        Article.objects.filter(article_id=key.split(':')[1]).update(click_nums=F('click_nums') + int(value))
        con.hdel('blog:visited:list', key)

    return True


@celery_app.task()
def commit_like():
    like = con.hgetall('blog:like:list')
    data = OrderedDict(like)
    for key, value in data.items():
        data = json.loads(value)
        user = User.objects.get(pk=data['user'])
        article_instance = Article.objects.get(pk=data['blog_id'])
        Like.objects.create(blog_id=article_instance, user=user)
        con.hdel('blog:like:list', key)

    return True


@celery_app.task()
def commit_comment():

    while con.llen('blog:comment:list:json'):
        data = con.blpop('blog:comment:list:json')
        value = json.loads(data[1])
        serializer = CommentSerializer(data=value)

        if not serializer.is_valid():
            return False
        serializer.save()

    return True
