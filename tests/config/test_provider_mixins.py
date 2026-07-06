"""Tests for Mixin composition in provider config base classes."""



class TestMixinComposition:
    """Verify each base class inherits expected fields from Mixins."""

    def test_llm_base_has_all_mixin_fields(self):
        from animetta.config.providers.llm.base import LLMBaseConfig
        fields = LLMBaseConfig.model_fields
        assert "api_key" in fields
        assert "model" in fields
        assert "base_url" in fields
        assert "temperature" in fields
        assert "max_tokens" in fields
        assert "type" in fields

    def test_asr_base_has_api_and_model(self):
        from animetta.config.providers.asr.base import ASRBaseConfig
        fields = ASRBaseConfig.model_fields
        assert "api_key" in fields
        assert "model" in fields
        assert "base_url" in fields
        assert "type" in fields
        assert "language" in fields

    def test_tts_base_has_api_and_model(self):
        from animetta.config.providers.tts.base import TTSBaseConfig
        fields = TTSBaseConfig.model_fields
        assert "api_key" in fields
        assert "model" in fields
        assert "type" in fields
        assert "voice" in fields
        assert "speed" in fields

    def test_vc_base_has_device(self):
        from animetta.config.providers.vc.base import VCBaseConfig
        fields = VCBaseConfig.model_fields
        assert "device" in fields
        assert "type" in fields

    def test_separation_base_has_device(self):
        from animetta.config.providers.separation.base import SeparationBaseConfig
        fields = SeparationBaseConfig.model_fields
        assert "device" in fields
        assert "type" in fields

    def test_vad_base_has_type(self):
        from animetta.config.providers.vad.base import VADBaseConfig
        fields = VADBaseConfig.model_fields
        assert "type" in fields
        assert "sample_rate" in fields

    def test_deepseek_inherits_all_from_mixins(self):
        from animetta.config.providers.llm.deepseek import DeepSeekLLMConfig
        fields = DeepSeekLLMConfig.model_fields
        assert "api_key" in fields
        assert "temperature" in fields
        assert "max_tokens" in fields
        assert "type" in fields
        assert "model" in fields
