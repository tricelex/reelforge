from __future__ import annotations

from rest_framework import serializers

from reelforge.clipping.models import ClipCandidate
from reelforge.clipping.models import ClipLayoutConfig
from reelforge.clipping.models import ClipMediaAsset
from reelforge.clipping.models import ClipMusicAsset
from reelforge.clipping.models import ClippingJob
from reelforge.clipping.models import ClipPost
from reelforge.clipping.models import ClipRender
from reelforge.clipping.models import ClipRenderStageResult
from reelforge.clipping.models import ClipRenderTemplate
from reelforge.clipping.models import ClipStyleConfig
from reelforge.clipping.models import ClipTimedOverlay


class ClipRenderStageResultSerializer(serializers.ModelSerializer):
    output_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipRenderStageResult
        fields = [
            "id", "stage_order", "stage_name", "status",
            "started_at", "completed_at", "duration_sec",
            "last_error", "output_file_url",
        ]
        read_only_fields = fields

    def get_output_file_url(self, obj: ClipRenderStageResult) -> str | None:
        if not obj.output_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.output_file.url)
        return obj.output_file.url


class ClipRenderSerializer(serializers.ModelSerializer):
    stage_results = ClipRenderStageResultSerializer(many=True, read_only=True)
    video_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipRender
        fields = [
            "id", "candidate", "format", "status", "paused_at_stage",
            "video_file_url", "file_size_bytes", "render_duration_sec",
            "include_captions", "include_title_card", "include_branding",
            "celery_task_id", "started_at", "completed_at", "last_error",
            "stage_results", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "paused_at_stage", "video_file_url",
            "file_size_bytes", "render_duration_sec", "celery_task_id",
            "started_at", "completed_at", "last_error", "stage_results",
            "created_at", "updated_at",
        ]

    def get_video_file_url(self, obj: ClipRender) -> str | None:
        if not obj.video_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.video_file.url)
        return obj.video_file.url


class ClipTimedOverlaySerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipTimedOverlay
        fields = [
            "id", "candidate", "overlay_type", "text", "image",
            "start_sec", "end_sec", "position_x", "position_y",
            "opacity", "font_size", "font_color", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClipLayoutConfigSerializer(serializers.ModelSerializer):
    preview_image_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipLayoutConfig
        fields = [
            "id", "candidate", "render_mode", "render_format",
            "manual_crop_x", "manual_crop_y", "manual_crop_w", "manual_crop_h",
            "region_a_label", "region_a_x", "region_a_y", "region_a_w", "region_a_h",
            "region_b_label", "region_b_x", "region_b_y", "region_b_w", "region_b_h",
            "stack_ratio", "face_detected", "detection_confidence",
            "preview_image_url", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "candidate", "face_detected", "detection_confidence",
            "preview_image_url", "created_at", "updated_at",
        ]

    def get_preview_image_url(self, obj: ClipLayoutConfig) -> str | None:
        if not obj.preview_image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.preview_image.url)
        return obj.preview_image.url


class ClipStyleConfigSerializer(serializers.ModelSerializer):
    preview_image_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipStyleConfig
        fields = [
            "id", "candidate", "render_template",
            "intro_asset", "outro_asset", "music_asset",
            # All style fields from ClipRenderStyleMixin:
            "caption_enabled", "caption_style", "caption_font", "caption_size",
            "caption_color", "caption_stroke_color", "caption_stroke_width",
            "caption_bg_color", "caption_position", "caption_animation",
            "caption_language", "caption_translate_to", "emoji_keyword_map",
            "hook_enabled", "hook_style", "hook_duration_sec", "hook_font",
            "hook_size", "hook_color", "hook_bg_color", "hook_animation",
            "intro_transition", "outro_transition", "transition_duration_sec",
            "watermark_enabled", "watermark_type", "watermark_text", "watermark_image",
            "watermark_position", "watermark_opacity", "watermark_size",
            "progress_bar_enabled", "progress_bar_position", "progress_bar_color",
            "progress_bar_height",
            "music_enabled", "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
            "translated_transcript_json", "preview_image_url",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "candidate", "preview_image_url", "created_at", "updated_at"]

    def get_preview_image_url(self, obj: ClipStyleConfig) -> str | None:
        if not obj.preview_image:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.preview_image.url)
        return obj.preview_image.url


class ClipCandidateListSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipCandidate
        fields = [
            "id", "clipping_job", "title", "start_sec", "end_sec", "duration_sec",
            "relevance_score", "status", "approved", "approved_at", "render_gates",
            "is_manual", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "duration_sec", "clipping_job", "is_manual", "created_at", "updated_at"]


class ClipCandidateDetailSerializer(serializers.ModelSerializer):
    layout_config = ClipLayoutConfigSerializer(read_only=True)
    style_config = ClipStyleConfigSerializer(read_only=True)
    timed_overlays = ClipTimedOverlaySerializer(many=True, read_only=True)

    class Meta:
        model = ClipCandidate
        fields = [
            "id", "clipping_job", "title", "hook_text", "caption_template",
            "start_sec", "end_sec", "duration_sec", "relevance_score",
            "reason", "transcript_excerpt", "status", "approved",
            "approved_at", "approved_by", "rejection_reason", "render_gates",
            "is_manual", "layout_config", "style_config", "timed_overlays",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "duration_sec", "clipping_job", "approved", "approved_at",
            "approved_by", "status", "is_manual", "layout_config", "style_config",
            "timed_overlays", "created_at", "updated_at",
        ]


class ClipCandidateSummarySerializer(serializers.ModelSerializer):
    """Minimal nested representation used inside ClippingJobDetailSerializer."""

    class Meta:
        model = ClipCandidate
        fields = [
            "id", "title", "start_sec", "end_sec", "duration_sec",
            "relevance_score", "status", "approved", "render_gates", "is_manual",
        ]
        read_only_fields = fields


class ClippingJobListSerializer(serializers.ModelSerializer):
    total_cost_usd = serializers.DecimalField(max_digits=10, decimal_places=6, read_only=True)

    class Meta:
        model = ClippingJob
        fields = [
            "id", "social_account", "source_type", "source_url", "source_video_file",
            "source_title", "source_duration_sec", "clips_requested", "skip_analysis", "status",
            "started_at", "completed_at", "failed_at", "last_error",
            "total_cost_usd", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "started_at", "completed_at", "failed_at",
            "last_error", "total_cost_usd", "source_title", "source_duration_sec",
            "created_at", "updated_at",
        ]


class ClippingJobDetailSerializer(ClippingJobListSerializer):
    candidates = ClipCandidateSummarySerializer(many=True, read_only=True)
    analysis_manifest = serializers.JSONField(read_only=True)

    class Meta(ClippingJobListSerializer.Meta):
        fields = [*ClippingJobListSerializer.Meta.fields, "transcript_text", "transcript_json", "analysis_manifest", "analysis_provider", "analysis_cost_usd", "agent_run_id", "celery_task_id", "candidates"]
        read_only_fields = [*ClippingJobListSerializer.Meta.read_only_fields, "transcript_text", "transcript_json", "analysis_manifest", "analysis_provider", "analysis_cost_usd", "agent_run_id", "celery_task_id", "candidates"]


class ClipRenderTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipRenderTemplate
        fields = [
            "id", "name", "is_default",
            "caption_enabled", "caption_style", "caption_font", "caption_size",
            "caption_color", "caption_stroke_color", "caption_stroke_width",
            "caption_bg_color", "caption_position", "caption_animation",
            "caption_language", "caption_translate_to", "emoji_keyword_map",
            "hook_enabled", "hook_style", "hook_duration_sec", "hook_font",
            "hook_size", "hook_color", "hook_bg_color", "hook_animation",
            "intro_transition", "outro_transition", "transition_duration_sec",
            "watermark_enabled", "watermark_type", "watermark_text",
            "watermark_position", "watermark_opacity", "watermark_size",
            "progress_bar_enabled", "progress_bar_position", "progress_bar_color",
            "progress_bar_height",
            "music_enabled", "music_volume_db", "music_fade_in_sec", "music_fade_out_sec",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClipMediaAssetSerializer(serializers.ModelSerializer):
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipMediaAsset
        fields = [
            "id", "asset_type", "name", "file", "duration_sec",
            "is_active", "thumbnail_url", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "duration_sec", "thumbnail_url", "created_at", "updated_at"]

    def get_thumbnail_url(self, obj: ClipMediaAsset) -> str | None:
        if not obj.thumbnail:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.thumbnail.url)
        return obj.thumbnail.url


class ClipMusicAssetSerializer(serializers.ModelSerializer):
    waveform_file_url = serializers.SerializerMethodField()

    class Meta:
        model = ClipMusicAsset
        fields = [
            "id", "name", "file", "duration_sec", "bpm", "genre",
            "is_active", "waveform_file_url", "created_at", "updated_at",
        ]
        read_only_fields = ["id", "duration_sec", "waveform_file_url", "created_at", "updated_at"]

    def get_waveform_file_url(self, obj: ClipMusicAsset) -> str | None:
        if not obj.waveform_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.waveform_file.url)
        return obj.waveform_file.url


class ClipPostSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClipPost
        fields = [
            "id", "render", "social_account", "caption", "title", "hashtags",
            "scheduled_at", "posted_at", "status", "platform_post_id",
            "platform_url", "celery_task_id", "last_error",
            "views", "likes", "comments", "shares", "revenue_est_usd",
            "last_analytics_sync", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "platform_post_id", "platform_url", "celery_task_id",
            "last_error", "views", "likes", "comments", "shares",
            "revenue_est_usd", "last_analytics_sync", "created_at", "updated_at",
        ]
