import json
import re
from hashlib import md5
from uuid import UUID
from django_filters.rest_framework import DjangoFilterBackend
from django_redis import get_redis_connection
from rest_framework.filters import OrderingFilter
from rest_framework import status, permissions
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin, UpdateModelMixin, CreateModelMixin, \
    DestroyModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ModelViewSet, ReadOnlyModelViewSet
from rest_framework.mixins import ListModelMixin
from sonsuz_website.blog.api.serializers import ArticleSerializer, CategorySerializer, CommentSerializer, \
    ArticleListSerializer, ArticleViewSerializer, LikeSerializer, CollectSerializer, CollectCategorySerializer, \
    CategoryFollowSerializer
from sonsuz_website.blog.models import Article, ArticleCategory, Comment, Like, Collect, CollectCategory, CategoryFollow
from sonsuz_website.users.models import User
from sonsuz_website.blog.api.pagination import PageLimitOffset


class ArticleListView(ListModelMixin, GenericViewSet):
    serializer_class = ArticleListSerializer
    queryset = Article.objects.all()
    # queryset = Article.objects.annotate(num_posts=Count('comments'))
    pagination_class = PageLimitOffset

    filter_backends = (DjangoFilterBackend, OrderingFilter)
    filter_fields = ('status', 'category', 'type')
    ordering_fields = ('created_at', 'click_nums')

    def list(self, request, *args, **kwargs):

        if 'username' not in request.query_params:
            queryset = self.filter_queryset(self.get_queryset())
        else:
            username = request.query_params["username"]
            user = User.objects.get(username=username).pk
            instance = Article.objects.filter(user=user)
            queryset = self.filter_queryset(instance)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)


class ArticleView(CreateModelMixin, RetrieveModelMixin, UpdateModelMixin, DestroyModelMixin, GenericViewSet):
    serializer_class = ArticleViewSerializer
    queryset = Article.objects.all()

    def handle_visited(self, request, id):
        increase_pv = False
        con = get_redis_connection()
        # article.id:{id}:visits
        visited_args = ("blog:visited:list", "article.id:{id}:num".format_map({'id': str(id)}))
        if not con.hget(*visited_args):
            con.hset(*visited_args, 0)

        if 'HTTP_X_FORWARDED_FOR' in request.META:
            ip = request.META['HTTP_X_FORWARDED_FOR']
            print('HTTP_X_FORWARDED_FOR', ip)
        else:
            ip = request.META['REMOTE_ADDR']
            print('REMOTE_ADDR', ip)
        flag = md5((ip + str(id)).encode("utf-8")).hexdigest()
        if not con.hget('visitor', flag):
            increase_pv = True
            # cache.set(flag, 1, 1 * 60)
            con.hset('blog:visitor:flag', flag, 1)
            con.expire('blog:visitor:flag', 60)

        if increase_pv:
            con.hincrby(*visited_args)

            # cache.client.hset("visited", str(id), 1)

    def retrieve(self, request, *args, **kwargs):

        self.handle_visited(request, self.get_object().article_id)

        collect_category = []
        collect_instance = Collect.objects.filter(user=request.user.pk, article=self.get_object().article_id)
        category_follow_instance = CategoryFollow.objects.filter(user=request.user.pk,
                                                                 category=self.get_object().category)

        if collect_instance:
            collect_serializer = CollectSerializer(data=collect_instance, many=True)
            collect_serializer.is_valid()
            collect_category = [str(i) for i in collect_serializer.data[0]['category']]

        con = get_redis_connection()
        flag = md5((str(request.user.pk) + str(self.get_object().article_id.hex)).encode("utf-8")).hexdigest()
        # userid:{userid}:article.id:{article.id}:json
        like_args = ('blog:like:list',
                     "userid:{userid}:article.id:{article_id}:json"
                     .format_map({'userid': request.user.pk,
                                  'article_id': self.get_object().article_id}))
        # if con.hexists('blog:like', "like.data:{flag}:json".format_map({'flag': flag})):
        if con.hexists(*like_args):
            is_like = True
        else:
            like_instance = Like.objects.filter(user=request.user.pk, blog_id=self.get_object().article_id)
            if like_instance:
                is_like = True
            else:
                is_like = False

        if collect_instance:
            is_collect = True
        else:
            is_collect = False

        if category_follow_instance:
            is_category_follow = True
        else:
            is_category_follow = False

        instance = self.get_object()
        con = get_redis_connection()
        click_nums = 0
        if con.hexists('visited', str(self.get_object().article_id)):
            click_nums = self.get_object().click_nums + int(con.hget('visited', str(self.get_object().article_id)))

        instance.click_nums += click_nums
        # instance.click_nums += 1
        # instance.save()
        serializer = self.get_serializer(instance)
        data = serializer.data
        data.update({'is_like': is_like})
        data.update({'is_collect': is_collect})
        data.update({'collect_category': collect_category})
        data.update({'is_category_follow': is_category_follow})
        return Response(data)

    def create(self, request, **kwargs):
        print(request.data)
        data = request.data
        data.update({'user': request.user.pk})
        if data['abstract'] == None:
            content = data['content']
            content = re.sub('!\[.*?\]\((.*?)\)', '', content)
            pattern = '[\\\`\*\_\[\]\#\+\-\!\>]'
            content = re.sub(pattern, '', content)
            abstract = content[0: 150]
            data.update({'abstract': abstract})

        serializer = ArticleSerializer(data=data)
        if not serializer.is_valid():
            return Response({'info': 'error'}, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)
        # return Response(serial.data)
        # return Response({'code': '200', 'message': 'OK'})


class CategoryViewSet(ModelViewSet):
    serializer_class = CategorySerializer
    queryset = ArticleCategory.objects.all()

    def list(self, request, *args, **kwargs):

        if 'username' not in request.query_params:
            queryset = self.filter_queryset(self.get_queryset())
        else:
            username = request.query_params["username"]
            user = User.objects.get(username=username).pk
            instance = ArticleCategory.objects.filter(user=user)
            queryset = self.filter_queryset(instance)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        category_follow_instance = CategoryFollow.objects.filter(user=request.user.pk, category=self.get_object().id)
        if category_follow_instance:
            is_category_follow = True
        else:
            is_category_follow = False
        serializer = self.get_serializer(instance)
        data = serializer.data
        data.update({'is_category_follow': is_category_follow})

        return Response(data)

    def create(self, request, *args, **kwargs):
        data = request.data
        data.update({'user': request.user.pk})

        serializer = CategorySerializer(data=data)
        if not serializer.is_valid():
            return Response({'info': 'error'}, status=status.HTTP_400_BAD_REQUEST)

        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


class CommentsViewSet(ModelViewSet):
    serializer_class = CommentSerializer
    queryset = Comment.objects.filter(reply_comment=None)
    filter_backends = (DjangoFilterBackend, )
    filter_fields = ('blog_id',)



    def create(self, request, *args, **kwargs):
        con = get_redis_connection()
        data = request.data
        data.update({'user': request.user.pk})
        comment_args = ['blog:comment:list:json']
        value = json.dumps(data)
        con.lpush(*comment_args, value)
        serializer = CommentSerializer(data=data)
        if not serializer.is_valid():
            return Response({'info': 'error'}, status=status.HTTP_400_BAD_REQUEST)
        #
        serializer.save()
        rlt_data = serializer.data
        print(rlt_data)
        rlt_data['avatar'] = 'http://localhost:8000' + rlt_data['avatar']
        return Response(rlt_data, status=status.HTTP_200_OK)


class LikeViewSet(ModelViewSet):
    serializer_class = LikeSerializer
    queryset = Like.objects.all()

    def create(self, request, *args, **kwargs):

        con = get_redis_connection()

        flag = md5((str(request.user.pk) + UUID(request.data['blog_id']).hex).encode("utf-8")).hexdigest()
        like_args = ('blog:like:list',
                     "userid:{userid}:article.id:{article_id}:json"
                     .format_map({'userid': request.user.pk,
                                  'article_id': request.data['blog_id']}))
        if con.hexists(*like_args):
            con.hdel(*like_args)
            return Response({'like': False}, status=status.HTTP_200_OK)
        else:
            data = request.data
            data.update({'user': request.user.pk})
            value = json.dumps(data)
            con.hset(*like_args, value)
            return Response({'like': True}, status=status.HTTP_200_OK)

        # instance = Like.objects.filter(user=request.user.pk, blog_id=request.data['blog_id'])
        #
        # if instance:
        #     instance.delete()
        #     return Response({'like': False}, status=status.HTTP_200_OK)
        # else:
        #
        #     data = request.data
        #     data.update({'user': request.user.pk})
        #     serializer = LikeSerializer(data=data)
        #     if not serializer.is_valid():
        #         return Response({'info': 'error'}, status=status.HTTP_400_BAD_REQUEST)
        #
        #     serializer.save()
        #     return Response({'like': True}, status=status.HTTP_200_OK)

    # def destroy(self, request, *args, **kwargs):
    #     instance = self.get_object()
    #
    #     self.perform_destroy(instance)
    #     return Response(status=status.HTTP_204_NO_CONTENT)


class CollectCategoryViewSet(ModelViewSet):
    serializer_class = CollectCategorySerializer
    queryset = CollectCategory.objects.all()

    filter_backends = (DjangoFilterBackend,)
    filter_fields = ('type',)

    def list(self, request, *args, **kwargs):

        if 'username' not in request.query_params:
            queryset = self.filter_queryset(self.get_queryset())
        else:
            username = request.query_params["username"]
            user = User.objects.get(username=username).pk
            instance = CollectCategory.objects.filter(user=user)
            queryset = self.filter_queryset(instance)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        data = request.data
        data.update({'user': request.user.pk})
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


class CollectViewSet(ModelViewSet):
    serializer_class = CollectSerializer
    queryset = Collect.objects.all()

    pagination_class = PageLimitOffset

    def list(self, request, *args, **kwargs):

        if 'collectcategory' not in request.query_params:
            queryset = self.filter_queryset(self.get_queryset())
        else:
            # username = request.query_params["username"]
            # user = User.objects.get(username=username).pk
            # instance = Collect.objects.filter(user=user, category=request.query_params["category"])
            instance = Collect.objects.filter(category=request.query_params["collectcategory"])
            queryset = self.filter_queryset(instance)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):

        data = request.data
        data.update({'user': request.user.pk})
        category = request.data['category']
        category = [eval(i) for i in category]
        data.update({'category': category})

        instance = Collect.objects.filter(user=request.user.pk, article=request.data['article']).first()
        if instance:
            if request.data['category']:
                _response = self.update(data, instance=instance)
                return _response
            else:
                instance.delete()
                return Response({'is_colletc': False})

        else:
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            data = serializer.data
            data.update({'is_collect': True})
            return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    #     # return Response({'message': 'ok'})

    def update(self, request, *args, **kwargs):
        print(request)

        instance = kwargs['instance']
        print(instance)
        partial = kwargs.pop('partial', False)
        # instance = self.get_object()
        serializer = self.get_serializer(instance, data=request, partial=partial)
        serializer.is_valid(raise_exception=True)

        self.perform_update(serializer)
        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}
        data = serializer.data
        data.update({'is_colletc': True})
        return Response(data)

        # return Response({'message': 'ok'})


class CategoryFollowViewSet(ModelViewSet):
    serializer_class = CategoryFollowSerializer
    queryset = CategoryFollow.objects.all()
    pagination_class = PageLimitOffset

    def create(self, request, *args, **kwargs):

        instance = CategoryFollow.objects.filter(user=request.user.pk, category=request.data['category'])
        if instance:
            instance.delete()
            return Response({'isCategoryFollow': False}, status=status.HTTP_200_OK)
        else:

            data = request.data
            data.update({'user': request.user.pk})
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            headers = self.get_success_headers(serializer.data)
            return Response({'isCategoryFollow': True}, status=status.HTTP_201_CREATED, headers=headers)

    def list(self, request, *args, **kwargs):

        if 'username' not in request.query_params:
            queryset = self.filter_queryset(self.get_queryset())
        else:
            username = request.query_params["username"]
            user = User.objects.get(username=username).pk
            instance = CategoryFollow.objects.filter(user=user)
            queryset = self.filter_queryset(instance)

        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)
