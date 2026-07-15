"""Conversation channels: adapters between transports and the agent.

Public API:

    from channels.telegram_channel import TelegramChannel, ChannelReply
"""

from .telegram_channel import ChannelReply, TelegramChannel

__all__ = ["ChannelReply", "TelegramChannel"]
