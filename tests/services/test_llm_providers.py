from __future__ import annotations

from animetta.config.providers.llm import (
    DeepSeekLLMConfig,
    GLMLLMConfig,
    LocalLoraLLMConfig,
    MockLLMConfig,
    OllamaLLMConfig,
    OpenAILLMConfig,
)
from animetta.services.llm import (
    GLMLLM,
    LLMFactory,
    LLMInterface,
    LocalLoraLLM,
    MockLLM,
    OllamaLLM,
    OpenAILLM,
)

"""
Tests for LLM provider implementations.

Covers:
- All providers implement LLMInterface ABC
- from_config classmethod creates instances with correct config
- MockLLM: from_config(), chat(), chat_stream(), close()
- OpenAILLM: from_config() creates instance (mock HTTP calls)
- GLMLLM: from_config() with config object, chat/chat_stream (mock)
- OllamaLLM: from_config(), chat/chat_stream via executor (mock)
- LocalLoraLLM: from_config() with local model paths (mock transformers)
- LLMFactory.create falls back to MockLLM on unknown provider
- LLMFactory.create_from_config creates correct type based on config type
"""

from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

# ── Helpers ──────────────────────────────────────────────────────


def _ensure_mock_module(name: str):
    """Create a fake module in sys.modules for optional deps."""
    import sys
    from unittest.mock import MagicMock

    if name not in sys.modules:
        sys.modules[name] = MagicMock()


# Create fake modules for optional dependencies that are imported
# inside methods (not at module level). This lets @patch work.
_ensure_mock_module("peft")
_ensure_mock_module("transformers")
_ensure_mock_module("faster_whisper")
_ensure_mock_module("zai")
_ensure_mock_module("funasr")
_ensure_mock_module("silero_vad")


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_config():
    """Create a MockLLMConfig with default values."""
    return MockLLMConfig()


@pytest.fixture
def openai_llm_config():
    """Create an OpenAILLMConfig with test values."""
    return OpenAILLMConfig(
        api_key="test-openai-key",
        model="gpt-4o-mini",
        temperature=0.5,
        top_p=0.92,
        max_tokens=500,
    )


@pytest.fixture
def glm_llm_config():
    """Create a GLMLLMConfig with test values."""
    return GLMLLMConfig(
        api_key="test-glm-key",
        model="glm-4-flash",
        temperature=0.3,
        max_tokens=2048,
    )


@pytest.fixture
def ollama_llm_config():
    """Create an OllamaLLMConfig with test values."""
    return OllamaLLMConfig(
        model="llama3",
        base_url="http://localhost:11434",
        temperature=0.7,
        max_tokens=4096,
    )


@pytest.fixture
def local_lora_llm_config():
    """Create a LocalLoraLLMConfig with test values."""
    return LocalLoraLLMConfig(
        base_model_name="Qwen/Qwen2.5-7B-Instruct",
        lora_path="models/lora/test-v1",
        device="cpu",
        temperature=0.7,
        max_tokens=512,
    )


# ── Interface Implementation Tests ──────────────────────────────


class TestLLMInterface:
    """Verify all providers implement the LLMInterface ABC correctly."""

    @staticmethod
    def _get_abstract_methods() -> set:
        """Return the set of abstract method names from LLMInterface."""
        abstract = set()
        for attr_name in dir(LLMInterface):
            attr = getattr(LLMInterface, attr_name, None)
            if getattr(attr, "__isabstractmethod__", False):
                abstract.add(attr_name)
        return abstract

    def test_all_providers_implement_interface(self):
        """
        All LLM provider classes should be concrete subclasses of LLMInterface.
        Uses direct module imports to handle optional deps.
        """
        providers = [MockLLM]
        # Try optional providers
        for mod_name, cls_name in [
            ("animetta.services.llm.glm_llm", "GLMLLM"),
            ("animetta.services.llm.openai_llm", "OpenAILLM"),
            ("animetta.services.llm.ollama_llm", "OllamaLLM"),
            ("animetta.services.llm.local_lora_llm", "LocalLoraLLM"),
        ]:
            try:
                import importlib

                mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name, None)
                if cls is not None:
                    providers.append(cls)
            except (ImportError, AttributeError):
                continue

        for provider_cls in providers:
            assert issubclass(provider_cls, LLMInterface), (
                f"{provider_cls.__name__} does not inherit from LLMInterface"
            )

    def test_all_abstract_methods_implemented(self):
        """Each concrete provider must implement every abstract method."""
        abstract_methods = self._get_abstract_methods()

        providers = [MockLLM]
        for mod_name, cls_name in [
            ("animetta.services.llm.glm_llm", "GLMLLM"),
            ("animetta.services.llm.openai_llm", "OpenAILLM"),
            ("animetta.services.llm.ollama_llm", "OllamaLLM"),
            ("animetta.services.llm.local_lora_llm", "LocalLoraLLM"),
        ]:
            try:
                import importlib

                mod = importlib.import_module(mod_name)
                cls = getattr(mod, cls_name, None)
                if cls is not None:
                    providers.append(cls)
            except (ImportError, AttributeError):
                continue

        for provider_cls in providers:
            for method in abstract_methods:
                impl = getattr(provider_cls, method, None)
                assert impl is not None, (
                    f"{provider_cls.__name__} is missing abstract method '{method}'"
                )
                assert not getattr(impl, "__isabstractmethod__", False), (
                    f"{provider_cls.__name__} has not implemented '{method}'"
                )


# ── MockLLM Tests ───────────────────────────────────────────────


class TestMockLLM:
    """Tests for the MockLLM provider."""

    @pytest.fixture(autouse=True)
    def _disable_simulated_processing_delay(self):
        with patch("asyncio.sleep", new=AsyncMock()):
            yield

    def test_from_config_returns_instance(self, mock_llm_config):
        """from_config should return a MockLLM instance."""
        instance = MockLLM.from_config(mock_llm_config, system_prompt="Hello")
        assert isinstance(instance, MockLLM)
        assert instance.system_prompt == "Hello"

    def test_from_config_default_system_prompt(self, mock_llm_config):
        """from_config should default to empty system_prompt if not provided."""
        instance = MockLLM.from_config(mock_llm_config)
        assert instance.system_prompt == ""

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat() should return a non-empty string."""
        llm = MockLLM(system_prompt="test")
        response = await llm.chat("Hello")
        assert isinstance(response, str)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_chat_includes_user_input(self):
        """chat() response should contain the user input."""
        llm = MockLLM()
        response = await llm.chat("Test input")
        assert "Test input" in response

    @pytest.mark.asyncio
    async def test_chat_updates_history(self):
        """chat() should add user and assistant messages to history."""
        llm = MockLLM()
        assert len(llm.get_history()) == 0
        await llm.chat("Hello")
        history = llm.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_chat_stream_yields_strings(self):
        """chat_stream() should yield character strings."""
        llm = MockLLM()
        chunks = []
        async for chunk in llm.chat_stream("Hello"):
            chunks.append(chunk)
        assert len(chunks) > 0
        assert all(isinstance(c, str) for c in chunks)

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should not raise."""
        llm = MockLLM()
        await llm.close()  # should not raise

    def test_set_system_prompt(self):
        """set_system_prompt should update the system prompt."""
        llm = MockLLM()
        llm.set_system_prompt("New prompt")
        assert llm.system_prompt == "New prompt"

    def test_get_history_returns_copy(self):
        """get_history() should return a copy, not the internal list."""
        llm = MockLLM()
        history = llm.get_history()
        history.append({"role": "user", "content": "injected"})
        assert len(llm.get_history()) == 0  # original unchanged

    def test_clear_history(self):
        """clear_history() should reset history and call_count."""
        llm = MockLLM()
        llm.history.append({"role": "user", "content": "x"})
        llm.call_count = 5
        llm.clear_history()
        assert llm.get_history() == []
        assert llm.call_count == 0

    def test_handle_interrupt_with_response(self):
        """handle_interrupt() with partial response should add to history."""
        llm = MockLLM()
        llm.history.append({"role": "user", "content": "hello"})
        llm.handle_interrupt("partial response")
        history = llm.get_history()
        assert len(history) == 3
        assert history[1]["content"] == "partial response"

    def test_handle_interrupt_empty(self):
        """handle_interrupt() with empty string should not modify history."""
        llm = MockLLM()
        llm.history.append({"role": "user", "content": "hello"})
        llm.handle_interrupt("")
        assert len(llm.get_history()) == 1

    def test_set_memory_from_history(self):
        """set_memory_from_history should not raise."""
        llm = MockLLM()
        llm.set_memory_from_history("conf_uid", "history_uid")  # should not raise


# ── OpenAILLM Tests ─────────────────────────────────────────────


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("openai"),
    reason="openai package not installed",
)
class TestOpenAILLM:
    """Tests for the OpenAILLM provider (all external calls mocked)."""

    @pytest.fixture(autouse=True)
    def _isolate_http_client_construction(self):
        with patch("httpx.AsyncClient"):
            yield

    def test_from_config_returns_instance(self, openai_llm_config):
        """from_config should return an OpenAILLM instance with correct config."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI"):
            instance = OpenAILLM.from_config(openai_llm_config, system_prompt="test")
        assert isinstance(instance, OpenAILLM)
        assert instance.api_key == "test-openai-key"
        assert instance.model == "gpt-4o-mini"
        assert instance.system_prompt == "test"
        assert instance.temperature == 0.5
        assert instance.top_p == 0.92
        assert instance.max_tokens == 500

    @pytest.mark.asyncio
    async def test_chat_passes_top_p_to_api(self):
        """chat() should pass top_p so realtime roleplay can use lively sampling."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "Mocked OpenAI response"
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock.return_value = mock_client

            llm = OpenAILLM(api_key="key", model="gpt-4", top_p=0.94)
            await llm.chat("Hello")

        call_kwargs = mock_client.chat.completions.create.await_args.kwargs
        assert call_kwargs["top_p"] == 0.94

    def test_from_config_supports_deepseek(self):
        """from_config should also work with DeepSeekLLMConfig."""

        config = DeepSeekLLMConfig(
            api_key="test-ds-key",
            model="deepseek-v4-flash",
            base_url="https://api.deepseek.com/v1",
        )
        with patch("animetta.services.llm.openai_llm.AsyncOpenAI"):
            instance = OpenAILLM.from_config(config, system_prompt="hello")
        assert instance.api_key == "test-ds-key"
        assert instance.model == "deepseek-v4-flash"
        assert instance.base_url == "https://api.deepseek.com/v1"

    def test_constructor_creates_client(self):
        """Constructor should initialize AsyncOpenAI client."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:
            instance = OpenAILLM(api_key="key", model="gpt-4")
        mock.assert_called_once_with(api_key="key", http_client=ANY)
        assert instance.client is not None

    def test_constructor_with_base_url(self):
        """Constructor should pass base_url to AsyncOpenAI."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:
            OpenAILLM(api_key="key", model="gpt-4", base_url="https://custom.example.com")
        mock.assert_called_once_with(
            api_key="key", http_client=ANY, base_url="https://custom.example.com"
        )

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat() should return a string from the mocked API."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "Mocked OpenAI response"
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock.return_value = mock_client

            llm = OpenAILLM(api_key="key", model="gpt-4")
            response = await llm.chat("Hello")
        assert response == "Mocked OpenAI response"

    @pytest.mark.asyncio
    async def test_chat_updates_history(self):
        """chat() should record user/assistant in history."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "response"
            mock_response.choices = [mock_choice]
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock.return_value = mock_client

            llm = OpenAILLM(api_key="key", model="gpt-4")
            await llm.chat("Hi")
        history = llm.get_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hi"

    @pytest.mark.asyncio
    async def test_chat_stream_yields_strings(self):
        """chat_stream() should yield strings from the mocked streaming API."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:

            async def mock_stream():
                for token in ["Hello", " ", "World"]:
                    chunk = MagicMock()
                    choice = MagicMock()
                    choice.delta.content = token
                    chunk.choices = [choice]
                    yield chunk

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
            mock.return_value = mock_client

            llm = OpenAILLM(api_key="key", model="gpt-4")
            chunks = []
            async for chunk in llm.chat_stream("Hi"):
                chunks.append(chunk)
        assert chunks == ["Hello", " ", "World"]

    @pytest.mark.asyncio
    async def test_chat_messages_stream_preserves_explicit_history(self):
        """Private message streaming must not mutate the provider's shared history."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:

            async def mock_stream():
                for token in ["private", " reply"]:
                    chunk = MagicMock()
                    choice = MagicMock()
                    choice.delta.content = token
                    chunk.choices = [choice]
                    yield chunk

            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_stream())
            mock.return_value = mock_client
            llm = OpenAILLM(api_key="key", model="gpt-4")
            llm.history.append({"role": "user", "content": "public turn"})
            messages = [{"role": "user", "content": "sandbox turn"}]

            chunks = [chunk async for chunk in llm.chat_messages_stream(messages)]

        assert chunks == ["private", " reply"]
        assert llm.history == [{"role": "user", "content": "public turn"}]
        call_kwargs = mock_client.chat.completions.create.await_args.kwargs
        assert call_kwargs["messages"] is messages
        assert call_kwargs["stream"] is True

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should call client.close()."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI") as mock:
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock.return_value = mock_client

            llm = OpenAILLM(api_key="key", model="gpt-4")
            await llm.close()
        mock_client.close.assert_awaited_once()

    def test_set_system_prompt(self):
        """set_system_prompt should update the system prompt."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI"):
            llm = OpenAILLM(api_key="key", model="gpt-4")
        llm.set_system_prompt("New prompt")
        assert llm.system_prompt == "New prompt"

    def test_history_methods(self):
        """clear_history should reset history."""

        with patch("animetta.services.llm.openai_llm.AsyncOpenAI"):
            llm = OpenAILLM(api_key="key", model="gpt-4")
        llm.history.append({"role": "user", "content": "x"})
        llm.clear_history()
        assert llm.get_history() == []


# ── GLMLLM Tests ────────────────────────────────────────────────


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("zhipuai"),
    reason="zhipuai package not installed",
)
class TestGLMLLM:
    """Tests for the GLMLLM provider (all external calls mocked)."""

    def test_from_config_returns_instance(self, glm_llm_config):
        """from_config should return a GLMLLM instance with the config."""
        instance = GLMLLM.from_config(glm_llm_config)
        assert isinstance(instance, GLMLLM)
        assert instance.config == glm_llm_config
        assert instance.config.api_key == "test-glm-key"
        assert instance.config.model == "glm-4-flash"

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat() should return a string via mocked ZhipuAI."""

        with patch("animetta.services.llm.glm_llm.ZhipuAI") as mock_zhipuai:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "Mocked GLM response"
            mock_response.choices = [mock_choice]
            mock_usage = MagicMock()
            mock_usage.prompt_tokens = 10
            mock_usage.completion_tokens = 20
            mock_response.usage = mock_usage
            mock_client.chat.completions.create = MagicMock(return_value=mock_response)
            mock_zhipuai.return_value = mock_client

            config = GLMLLMConfig(api_key="test-key")
            llm = GLMLLM(config=config)
            response = await llm.chat("Hello")
        assert response == "Mocked GLM response"

    @pytest.mark.asyncio
    async def test_chat_stream_yields_strings(self):
        """chat_stream() should yield strings via mocked ZhipuAI."""

        with patch("animetta.services.llm.glm_llm.ZhipuAI") as mock_zhipuai:
            mock_client = MagicMock()
            chunk1 = MagicMock()
            chunk1.choices[0].delta.content = "Hello"
            chunk2 = MagicMock()
            chunk2.choices[0].delta.content = " World"
            mock_client.chat.completions.create = MagicMock(return_value=[chunk1, chunk2])
            mock_zhipuai.return_value = mock_client

            config = GLMLLMConfig(api_key="test-key")
            llm = GLMLLM(config=config)
            chunks = []
            async for chunk in llm.chat_stream("Hi"):
                chunks.append(chunk)
        assert len(chunks) > 0

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should set client to None."""

        config = GLMLLMConfig(api_key="test-key")
        with patch("animetta.services.llm.glm_llm.ZhipuAI"):
            llm = GLMLLM(config=config)
        await llm.close()
        assert llm.client is None

    @pytest.mark.asyncio
    async def test_chat_updates_history(self):
        """chat() should track conversation history."""

        with patch("animetta.services.llm.glm_llm.ZhipuAI") as mock_zhipuai:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_choice = MagicMock()
            mock_choice.message.content = "response"
            mock_response.choices = [mock_choice]
            mock_usage = MagicMock()
            mock_usage.prompt_tokens = 5
            mock_usage.completion_tokens = 10
            mock_response.usage = mock_usage
            mock_client.chat.completions.create = MagicMock(return_value=mock_response)
            mock_zhipuai.return_value = mock_client

            config = GLMLLMConfig(api_key="test-key")
            llm = GLMLLM(config=config)
            await llm.chat("First message")
        assert len(llm.get_history()) == 2
        assert llm.get_history()[0]["role"] == "user"


# ── OllamaLLM Tests ─────────────────────────────────────────────


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("ollama"),
    reason="ollama package not installed",
)
class TestOllamaLLM:
    """Tests for the OllamaLLM provider (all external calls mocked)."""

    def test_from_config_returns_instance(self, ollama_llm_config):
        """from_config should return an OllamaLLM instance."""

        with patch("animetta.services.llm.ollama_llm.ollama"):
            instance = OllamaLLM.from_config(ollama_llm_config, system_prompt="test")
        assert isinstance(instance, OllamaLLM)
        assert instance.model == "llama3"
        assert instance.base_url == "http://localhost:11434"
        assert instance.system_prompt == "test"
        assert instance.temperature == 0.7

    def test_from_config_raises_on_wrong_type(self, openai_llm_config):
        """from_config should raise TypeError for wrong config type."""
        with pytest.raises(TypeError, match="OllamaLLMConfig"):
            OllamaLLM.from_config(openai_llm_config)

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat() should return a string."""

        with patch("animetta.services.llm.ollama_llm.ollama") as mock_ollama:
            mock_ollama_client = MagicMock()
            mock_ollama.Client.return_value = mock_ollama_client
            mock_ollama_client.chat.return_value = {
                "message": {"content": "Mocked Ollama response"}
            }

            llm = OllamaLLM(model="llama3")
            response = await llm.chat("Hello")
        assert response == "Mocked Ollama response"

    @pytest.mark.asyncio
    async def test_chat_stream_yields_strings(self):
        """chat_stream() should yield strings."""

        with patch("animetta.services.llm.ollama_llm.ollama") as mock_ollama:
            mock_ollama_client = MagicMock()
            mock_ollama.Client.return_value = mock_ollama_client

            def stream_chunks():
                yield {"message": {"content": "Hello"}}
                yield {"message": {"content": " "}}
                yield {"message": {"content": "World"}}

            mock_ollama_client.chat.return_value = stream_chunks()

            llm = OllamaLLM(model="llama3")
            chunks = []
            async for chunk in llm.chat_stream("Hi"):
                chunks.append(chunk)
        assert chunks == ["Hello", " ", "World"]

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should not raise."""

        with patch("animetta.services.llm.ollama_llm.ollama"):
            llm = OllamaLLM(model="llama3")
        await llm.close()  # should not raise

    def test_history_methods(self):
        """clear_history should reset, get_history should return copy."""

        with patch("animetta.services.llm.ollama_llm.ollama"):
            llm = OllamaLLM(model="llama3")
        llm.history.append({"role": "user", "content": "x"})
        assert len(llm.get_history()) == 1
        llm.clear_history()
        assert llm.get_history() == []


# ── LocalLoraLLM Tests ──────────────────────────────────────────


# LocalLoraLLM needs torch. Check if it's available and skip if not.
_torch_available = __import__("importlib").util.find_spec("torch") is not None


@pytest.mark.skipif(not _torch_available, reason="torch package not installed")
class TestLocalLoraLLM:
    """Tests for the LocalLoraLLM provider (all external calls mocked)."""

    def test_from_config_returns_instance(self, local_lora_llm_config):
        """from_config should return a LocalLoraLLM instance."""

        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("transformers.AutoModelForCausalLM"),
            patch("transformers.AutoTokenizer") as mock_tok,
            patch("peft.PeftModel"),
        ):
            mock_tokenizer_instance = MagicMock()
            mock_tokenizer_instance.pad_token = None
            mock_tokenizer_instance.eos_token = "<eos>"
            mock_tok.from_pretrained.return_value = mock_tokenizer_instance

            instance = LocalLoraLLM.from_config(local_lora_llm_config, system_prompt="test")
        assert isinstance(instance, LocalLoraLLM)
        assert instance.base_model_name == "Qwen/Qwen2.5-7B-Instruct"
        assert instance.lora_path == "models/lora/test-v1"
        assert instance.device == "cpu"
        assert instance.system_prompt == "test"

    def test_constructor_loads_model(self):
        """Constructor should trigger model loading."""

        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("transformers.AutoModelForCausalLM"),
            patch("transformers.AutoTokenizer") as mock_tok,
            patch("peft.PeftModel"),
        ):
            mock_tokenizer_instance = MagicMock()
            mock_tokenizer_instance.pad_token = None
            mock_tokenizer_instance.eos_token = "<eos>"
            mock_tok.from_pretrained.return_value = mock_tokenizer_instance

            llm = LocalLoraLLM(
                base_model_name="test-model",
                lora_path="test-lora",
                device="cpu",
            )
        assert llm._loaded is True
        assert llm.model is not None

    @pytest.mark.asyncio
    async def test_chat_returns_string(self):
        """chat() should return a string."""

        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("transformers.AutoModelForCausalLM"),
            patch("transformers.AutoTokenizer") as mock_tok,
            patch("peft.PeftModel"),
        ):
            mock_tokenizer_instance = MagicMock()
            mock_tokenizer_instance.pad_token = None
            mock_tokenizer_instance.eos_token = "<eos>"
            mock_tok.from_pretrained.return_value = mock_tokenizer_instance
            mock_tokenizer_instance.apply_chat_template.return_value = "formatted prompt"
            mock_inputs = MagicMock()
            mock_inputs.input_ids.shape = [1, 5]
            mock_tokenizer_instance.return_value = mock_inputs

            mock_model = MagicMock()
            mock_model.generate.return_value = [[101, 102, 103]]
            mock_tokenizer_instance.decode.return_value = "Mocked local response"

            # We mock PeftModel.from_pretrained to return our mock
            import peft

            peft.PeftModel.from_pretrained.return_value = mock_model

            llm = LocalLoraLLM(base_model_name="test", lora_path="test", device="cpu")
            response = await llm.chat("Hello")
        assert isinstance(response, str)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_close(self):
        """close() should release resources."""

        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("transformers.AutoModelForCausalLM"),
            patch("transformers.AutoTokenizer") as mock_tok,
            patch("peft.PeftModel"),
        ):
            mock_tokenizer_instance = MagicMock()
            mock_tokenizer_instance.pad_token = None
            mock_tokenizer_instance.eos_token = "<eos>"
            mock_tok.from_pretrained.return_value = mock_tokenizer_instance

            llm = LocalLoraLLM(base_model_name="test", lora_path="test", device="cpu")
            await llm.close()
        assert llm.model is None
        assert llm.tokenizer is None
        assert llm._loaded is False

    def test_history_methods(self):
        """history methods should work correctly."""

        with (
            patch("torch.cuda.is_available", return_value=False),
            patch("transformers.AutoModelForCausalLM"),
            patch("transformers.AutoTokenizer") as mock_tok,
            patch("peft.PeftModel"),
        ):
            mock_tokenizer_instance = MagicMock()
            mock_tokenizer_instance.pad_token = None
            mock_tokenizer_instance.eos_token = "<eos>"
            mock_tok.from_pretrained.return_value = mock_tokenizer_instance

            llm = LocalLoraLLM(base_model_name="test", lora_path="test", device="cpu")
        llm.history.append({"role": "user", "content": "x"})
        assert len(llm.get_history()) == 1
        assert llm.get_history()[0]["content"] == "x"
        llm.clear_history()
        assert llm.get_history() == []


# ── LLMFactory Tests ────────────────────────────────────────────


class TestLLMFactory:
    """Tests for the LLMFactory."""

    @patch("animetta.services.llm.factory.ProviderRegistry.create_service")
    def test_create_from_config_returns_correct_type(self, mock_create_service, openai_llm_config):
        """create_from_config should return the type returned by ProviderRegistry."""

        mock_llm = MagicMock()
        mock_create_service.return_value = mock_llm

        result = LLMFactory.create_from_config(openai_llm_config, system_prompt="test")
        mock_create_service.assert_called_once_with("llm", openai_llm_config, system_prompt="test")
        assert result is not None

    @patch("animetta.services.llm.factory.ProviderRegistry.create_service")
    def test_create_from_config_fallback_to_mock(self, mock_create_service):
        """create_from_config should fall back to MockLLM on error."""

        mock_create_service.side_effect = ValueError("Unknown provider")
        config = MockLLMConfig()

        result = LLMFactory.create_from_config(config, system_prompt="fallback")
        assert isinstance(getattr(result, "_target", result), MockLLM)

    @patch("animetta.services.llm.factory.LLMFactory.create_from_config")
    def test_create_uses_mock_for_unknown_provider(self, mock_create_from_config):
        """create() should use MockLLM for unknown provider names."""

        LLMFactory.create("unknown_provider", system_prompt="test")
        args, kwargs = mock_create_from_config.call_args
        config = args[0]
        assert isinstance(config, MockLLMConfig)

    @patch("animetta.services.llm.factory.LLMFactory.create_from_config")
    def test_create_openai(self, mock_create_from_config):
        """create() with 'openai' should build OpenAILLMConfig."""

        LLMFactory.create("openai", api_key="key-123", model="gpt-4")
        config = mock_create_from_config.call_args[0][0]
        assert isinstance(config, OpenAILLMConfig)
        assert config.api_key == "key-123"
        assert config.model == "gpt-4"

    @patch("animetta.services.llm.factory.LLMFactory.create_from_config")
    def test_create_glm(self, mock_create_from_config):
        """create() with 'glm' should build GLMLLMConfig."""

        LLMFactory.create("glm", api_key="key-456", model="glm-4")
        config = mock_create_from_config.call_args[0][0]
        assert isinstance(config, GLMLLMConfig)
        assert config.api_key == "key-456"
        assert config.model == "glm-4"

    @patch("animetta.services.llm.factory.LLMFactory.create_from_config")
    def test_create_ollama(self, mock_create_from_config):
        """create() with 'ollama' should build OllamaLLMConfig."""

        LLMFactory.create("ollama", model="mistral")
        config = mock_create_from_config.call_args[0][0]
        assert isinstance(config, OllamaLLMConfig)
        assert config.model == "mistral"
        assert config.base_url == "http://localhost:11434"

    @patch("animetta.services.llm.factory.LLMFactory.create_from_config")
    def test_create_mock(self, mock_create_from_config):
        """create() with 'mock' should build MockLLMConfig."""

        LLMFactory.create("mock")
        config = mock_create_from_config.call_args[0][0]
        assert isinstance(config, MockLLMConfig)

    def test_get_available_configs(self):
        """get_available_configs should return the stable implementation catalog."""

        providers = LLMFactory.get_available_configs()
        assert set(providers) == {
            "mock",
            "glm",
            "ollama",
            "openai",
            "deepseek",
            "local_lora",
        }
