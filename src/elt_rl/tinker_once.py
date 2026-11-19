"""Disable operation submission retries in the pinned Tinker SDK."""

from contextlib import ExitStack, contextmanager
from importlib.metadata import version
from unittest.mock import patch

from tinker._client import AsyncTinker
from tinker.lib.internal_client_holder import InternalClientHolder
from tinker.lib.public_interfaces.sampling_client import SamplingClient


@contextmanager
def single_attempt_sdk():
    """Keep normal future polling, but submit each operation at most once."""
    if version("tinker") != "0.39.2":
        raise RuntimeError("single-attempt submission is only audited for Tinker SDK 0.39.2")
    original_init = AsyncTinker.__init__
    original_sample = SamplingClient._send_asample_request

    def http_init(self, *args, **kwargs):
        kwargs["max_retries"] = 0
        original_init(self, *args, **kwargs)

    async def submit_once(self, operation, *args, **kwargs):
        return await operation(*args, **kwargs)

    async def sample_once(self, *args, **kwargs):
        response = await original_sample(self, *args, **kwargs)
        if response is None:
            # The SDK normally resubmits on backpressure or a billing pause.
            raise RuntimeError("Tinker declined the sample; automatic resubmission is disabled")
        return response

    with ExitStack() as stack:
        stack.enter_context(patch.object(AsyncTinker, "__init__", http_init))
        stack.enter_context(patch.object(InternalClientHolder, "execute_with_retries", submit_once))
        stack.enter_context(patch.object(SamplingClient, "_send_asample_request", sample_once))
        yield
