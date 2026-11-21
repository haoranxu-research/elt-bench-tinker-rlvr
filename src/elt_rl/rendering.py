"""Build the pinned Cookbook text-only renderer for the default ELT model."""

from tinker_cookbook.renderers import get_renderer
from tinker_cookbook.renderers.base import Renderer
from tinker_cookbook.tokenizer_utils import get_tokenizer

from .settings import DEFAULT_MODEL, DEFAULT_RENDERER

QWEN_TOKENIZER_REVISION = "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a"
QWEN_TOKENIZER_REVISIONS = {
    DEFAULT_MODEL: QWEN_TOKENIZER_REVISION,
    "Qwen/Qwen3.5-9B": "c202236235762e1c871ad0ccb60c8ee5ba337b9a",
    "Qwen/Qwen3.6-35B-A3B": "345d467b117d1fd5eda9b879a5988de9ae5f47a7",
}


def make_renderer(model: str, renderer: str, *, offline: bool = False) -> Renderer:
    if model in QWEN_TOKENIZER_REVISIONS and renderer in {DEFAULT_RENDERER, "qwen3_5"}:
        from tinker_cookbook.renderers.qwen3_5 import Qwen3_5DisableThinkingRenderer, Qwen3_5Renderer
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(
            model, revision=QWEN_TOKENIZER_REVISIONS[model], local_files_only=offline,
            trust_remote_code=False, token=False,
        )
        constructor = Qwen3_5DisableThinkingRenderer if renderer == DEFAULT_RENDERER else Qwen3_5Renderer
        return constructor(tokenizer)
    return get_renderer(renderer, get_tokenizer(model), model_name=model)
