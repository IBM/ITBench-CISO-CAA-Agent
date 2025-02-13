# Copyright contributors to the ITBench project. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import json

from crewai import LLM
from langchain.schema import HumanMessage, SystemMessage
from langchain_ibm import ChatWatsonx
from langchain_openai import ChatOpenAI, AzureChatOpenAI

api_domain_watsonx = "cloud.ibm.com"
api_domain_azure = "azure.com"
api_domain_azure_api = "azure-api.net"

def init_agent_llm(model: str = "", api_url: str = "", api_key: str = ""):
    model = model or os.getenv("LLM_MODEL_NAME") or os.getenv("OPENAI_MODEL_NAME")
    if not model:
        raise ValueError("Env variable `OPENAI_MODEL_NAME` is not set")

    # get API URL
    api_url = api_url or os.getenv("LLM_BASE_URL") or os.getenv("MODEL_API_URL")

    # get API key (if API is ollama, API key is not necessary)
    api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

    temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))

    llm = None
    if is_watsonx_api(api_url=api_url):
        proj_id = get_watsonx_project_id()
        set_watsonx_env_vars(model, api_url, api_key, proj_id)
        params = get_watsonx_model_params(model=model)
        llm = LLM(
            model="watsonx/" + model,
            base_url=api_url,
            api_key=api_key,
            **params,
        )
    elif is_azure_api(api_url=api_url):
        params = get_params_from_env()
        kwargs = {}
        if "api-version" in params:
            kwargs["api_version"] = params["api-version"]
        llm = LLM(
            model="azure/" + model,
            base_url=api_url,
            api_key=api_key,
            **kwargs,
        )
    else:
        llm = LLM(
            model=model,
            base_url=api_url,
            api_key=api_key,
            temperature=temperature,
        )
    return llm


def init_llm(model: str = "", api_url: str = "", api_key: str = ""):
    model = model or os.getenv("LLM_MODEL_NAME") or os.getenv("OPENAI_MODEL_NAME")
    if not model:
        raise ValueError("Env variable `OPENAI_MODEL_NAME` is not set")

    # get API URL
    api_url = api_url or os.getenv("LLM_BASE_URL") or os.getenv("MODEL_API_URL")

    # get API key (if API is ollama, API key is not necessary)
    api_key = api_key or os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")

    temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))

    if is_watsonx_api(api_url=api_url):
        # For Granite / Llama model, use WatsonX interface
        proj_id = get_watsonx_project_id()
        return init_watsonx_llm(model, api_url, api_key, proj_id)
    elif is_azure_api(api_url=api_url):
        params = get_params_from_env()
        kwargs = {}
        if "api-version" in params:
            kwargs["api_version"] = params["api-version"]
        return AzureChatOpenAI(temperature=temperature, model=model, api_key=api_key, base_url=api_url, **kwargs)
    elif "gpt" in model.lower():
        return ChatOpenAI(temperature=temperature, model=model, api_key=api_key, base_url=api_url)

    return None


def init_watsonx_llm(model: str = "", api_url: str = "", api_key: str = "", proj_id: str = ""):
    set_watsonx_env_vars(model, api_url, api_key, proj_id)
    params = get_watsonx_model_params(model=model)
    llm = ChatWatsonx(
        model_id=model,
        url=api_url,
        apikey=api_key,
        project_id=proj_id,
        params=params,
    )
    return llm


def is_watsonx_api(api_url: str):
    return api_url and api_domain_watsonx in api_url


def is_azure_api(api_url: str):
    return api_url and (api_domain_azure in api_url or api_domain_azure_api in api_url)


def get_params_from_env():
    params_str = os.getenv("LLM_PARAMS", "{}")
    params = {}
    try:
        params = json.loads(params_str)
    except Exception:
        pass
    return params


def get_watsonx_model_params(model: str):
    temperature = float(os.getenv("LLM_TEMPERATURE", "0.0"))

    # Parameters for Granite 3.x
    granite_3_params = {
        "temperature": temperature,
        "max_new_tokens": 4096,
        "repetition_penalty": 1,
        "decoding_method": "greedy"
    }
    # Parameters for Llama-3-1-70b-instruct
    llama_3_1_70b_params = {"temperature": temperature, "max_new_tokens": 8192}
    # Parameters for Llama-3-405b-instruct
    llama_3_405b_params = {"temperature": temperature, "max_new_tokens": 4096}
    # Parameters for Mixtral-8x7b-instruct
    mixtral_8x7b_params = {"temperature": temperature, "max_new_tokens": 4096}

    _model = model.lower()
    params = {"temperature": temperature}
    if "granite" in _model:
        params = granite_3_params
    elif "llama" in _model:
        if "70b" in _model:
            params = llama_3_1_70b_params
        elif "405b" in _model:
            params = llama_3_405b_params
        else:
            # use 4k token limit as default
            params = llama_3_405b_params
    elif "mixtral" in _model or "mistral" in _model:
        params = mixtral_8x7b_params
    return params


def get_watsonx_project_id():
    if "WATSONX_PROJECT_ID" not in os.environ:
        raise ValueError("Env variable `WATSONX_PROJECT_ID` must be set to use Granite model on WatsonX")
    proj_id = os.getenv("WATSONX_PROJECT_ID")
    return proj_id


def set_watsonx_env_vars(model: str = "", api_url: str = "", api_key: str = "", proj_id: str = ""):
    os.environ["WATSONX_APIKEY"] = api_key
    os.environ["WATSONX_URL"] = api_url
    os.environ["WATSONX_PROJECT_ID"] = proj_id
    return


def call_llm(prompt: str, model: str = "", api_key: str = "", api_url: str = "") -> str:
    _llm = init_llm(model=model, api_key=api_key, api_url=api_url)
    if not _llm:
        _llm = ChatOpenAI(temperature=0, model=model)

    model_lower = model.lower()
    system_prompt = ""
    if "llama" in model_lower:
        system_prompt = """<|start_of_role|>system<|end_of_role|>You always answer the questions with markdown formatting using GitHub syntax.
The markdown formatting you support: headings, bold, italic, links, tables, lists, code blocks, and blockquotes.
You must omit that you answer the questions with markdown.

Any HTML tags must be wrapped in block quotes, for example ```<html>```.
You will be penalized for not rendering code in block quotes.

When returning code blocks, specify language.

You are a helpful, respectful and honest assistant.
Always answer as helpfully as possible, while being safe.
Your answers should not include any harmful, unethical, racist, sexist, toxic, dangerous, or illegal content.
Please ensure that your responses are socially unbiased and positive in nature.
If a question does not make any sense, or is not factually coherent, explain why instead of answering something not correct.
If you don't know the answer to a question, please don't share false information.
<|end_of_text|>
<|start_of_role|>assistant<|end_of_role|>
"""
    elif "granite" in model_lower:
        system_prompt = """<|start_of_role|>system<|end_of_role|>You are Granite, an AI language model developed by IBM in 2024.
You are a cautious assistant. You carefully follow instructions.
You are helpful and harmless and you follow ethical guidelines and promote positive behavior.
<|end_of_text|>
<|start_of_role|>assistant<|end_of_role|>
"""
    elif "mixtral" in model_lower:
        # Mixtral does not accept `system prompt`. Instead, extend the user prompt like the following.
        prompt = f"""<s>[INST] You are Mixtral Chat, an AI language model developed by Mistral AI.
You are a cautious assistant. You carefully follow instructions.
You are helpful and harmless and you follow ethical guidelines and promote positive behavior. [INST]</s>
[INST] {prompt} [INST]</s>
"""

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))

    messages.append(HumanMessage(content=prompt))

    response = _llm.invoke(messages)
    answer = response.content
    # print("[DEBUG] answer:", answer)
    return answer


def extract_code(txt: str, separator: str = "```", code_type: str = "yaml"):
    if separator not in txt:
        raise ValueError(f"failed to extract code block from the text: {txt}")
    _tmp = txt.split(separator, 1)[-1]
    _tmp = _tmp.lstrip(code_type)
    code = _tmp.split(separator, 1)[0]
    return code
