"""Build the pinned Cookbook text-only renderer for the default ELT model."""

from tinker_cookbook.renderers import get_renderer
from tinker_cookbook.renderers.base import Renderer
from tinker_cookbook.tokenizer_utils import get_tokenizer

from .settings import DEFAULT_MODEL, DEFAULT_RENDERER

QWEN_TOKENIZER_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
QWEN_TOKENIZER_REVISIONS = {
    DEFAULT_MODEL: QWEN_TOKENIZER_REVISION,
    "Qwen/Qwen3.5-9B": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
}


def make_renderer(model: str, renderer: str, *, offline: bool = False) -> Renderer:
    if model in QWEN_TOKENIZER_REVISIONS and renderer == DEFAULT_RENDERER:
        from tinker_cookbook.renderers.qwen3_5 import Qwen3_5DisableThinkingRenderer
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            model, revision=QWEN_TOKENIZER_REVISIONS[model], local_files_only=offline,
            trust_remote_code=False, token=False,
        )
        return Qwen3_5DisableThinkingRenderer(tokenizer)
    return get_renderer(renderer, get_tokenizer(model), model_name=model)
