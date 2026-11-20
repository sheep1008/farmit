from django.contrib import admin

from chat.models import ChatMessage, ChatSession


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'created_at')
    readonly_fields = ('user', 'title', 'created_at')


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'role', 'intent', 'input_tokens', 'output_tokens', 'latency_ms', 'created_at')
    list_filter = ('role', 'intent')
