from __future__ import annotations

"""
LLM (Large Language Model) service interface definition
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class LLMInterface(ABC):
    """
    Abstract base class for LLM service interface
    All LLM implementations must inherit from this class and implement its abstract methods
    """

    @abstractmethod
    async def chat(self, user_input: str, **kwargs) -> str:
        """
        Chat with the LLM

        Args:
            user_input: User input
            **kwargs: Additional parameters

        Returns:
            str: LLM response
        """
        pass

    async def chat_messages(self, messages: list[dict], **kwargs) -> str:
        """Use only the supplied messages and never read or mutate shared history."""
        del messages, kwargs
        raise NotImplementedError("provider must implement history-neutral chat_messages")

    async def chat_messages_stream(
        self, messages: list[dict[str, str]], **kwargs: Any
    ) -> AsyncIterator[str]:
        """Stream a history-neutral messages request when supported.

        Providers without a native messages stream return one complete chunk.
        This keeps private internal calls off the provider's shared chat history.
        """
        response = await self.chat_messages(messages, **kwargs)
        if response:
            yield response

    @abstractmethod
    def chat_stream(self, user_input: str, **kwargs) -> AsyncIterator[str]:
        """
        Streaming chat

        Args:
            user_input: User input
            **kwargs: Additional parameters

        Yields:
            str: Text chunk of the LLM response
        """
        raise NotImplementedError

    @abstractmethod
    def set_system_prompt(self, prompt: str) -> None:
        """
        Set the system prompt

        Args:
            prompt: System prompt
        """
        pass

    @abstractmethod
    def get_history(self) -> list[dict[str, Any]]:
        """
        Get conversation history

        Returns:
            List[Dict[str, Any]]: Conversation history list
        """
        pass

    @abstractmethod
    def clear_history(self) -> None:
        """Clear conversation history"""
        pass

    @staticmethod
    def _trim_history(history: list[Any], max_messages: int) -> list[Any]:
        """Bound ``history`` to the last ``max_messages`` entries (context-bloat guard)."""
        if max_messages > 0 and len(history) > max_messages:
            return history[-max_messages:]
        return history

    @abstractmethod
    async def close(self) -> None:
        """Clean up resources"""
        pass

    @abstractmethod
    def handle_interrupt(self, heard_response: str = "") -> None:
        """
        Handle user interruption

        Args:
            heard_response: Partial response heard by the user (can be used for history storage)
        """
        pass

    @abstractmethod
    def set_memory_from_history(self, conf_uid: str, history_uid: str) -> None:
        """
        Restore conversation memory from history records

        Args:
            conf_uid: Config UID
            history_uid: History UID
        """
        pass
