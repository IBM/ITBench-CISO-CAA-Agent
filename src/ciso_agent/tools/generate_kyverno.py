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

import json
import os
from typing import Callable, Union

from ciso_agent.llm import get_llm_params, call_llm, extract_code
from ciso_agent.tools.utils import trim_quote
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class GenerateKyvernoToolInput(BaseModel):
    sentence: Union[str, dict] = Field(
        description="A short description of Kyverno policy to be generated. This includes what is validated with the Kyverno policy."
    )
    policy_file: str = Field(description="filepath for the Kyverno policy to be saved.")
    current_policy_file: Union[str, None] = Field(
        description="filepath of the current Kyverno policy to be updated. Only needed when updating an existing policy", default=""
    )


class GenerateKyvernoTool(BaseTool):
    name: str = "GenerateKyvernoTool"
    # correct description
    description: str = (
        "The tool to generate a Kyverno policy. This tool returns the generated Kyverno policy. "
        "This can be used for updating existing Kyverno policy."
    )

    args_schema: type[BaseModel] = GenerateKyvernoToolInput

    # disable cache
    cache_function: Callable = lambda _args, _result: False

    workdir: str = ""

    def __init__(self, **kwargs):
        super_args = {k: v for k, v in kwargs.items() if k not in ["workdir"]}
        super().__init__(**super_args)
        if "workdir" in kwargs:
            self.workdir = kwargs["workdir"]

    def _run(self, sentence: Union[str, dict], policy_file: str, current_policy_file: str = "") -> str:
        print("GenerateKyvernoTool is called")
        policy_file = trim_quote(policy_file)
        current_policy_file = trim_quote(current_policy_file)

        if current_policy_file and current_policy_file == "None":
            current_policy_file = None

        spec = sentence
        if isinstance(spec, dict):
            try:
                spec = json.dumps(spec, indent=2)
            except Exception:
                pass

        current_policy_block = ""
        if current_policy_file:
            current_policy = ""
            fpath = os.path.join(self.workdir, current_policy_file)
            with open(fpath, "r") as f:
                current_policy = f.read()
            current_policy_block = f"""Please update the following current policy:
```yaml
{current_policy}
```

"""

        prompt = f"""Generate a very simple Kyverno policy to do the following:
{spec}

{current_policy_block}

---
The following is an example of a Kyverno Policy to disallow Pod creation in `default` namespace
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-default-namespace
spec:
  rules:
  - name: validate-namespace
    match:
      any:
      - resources:
          kinds:
          - Pod
    validate:
      message: "Using 'default' namespace is not allowed."
      pattern:
        metadata:
          namespace: "!default"
```
"""
        model, api_key, api_url = get_llm_params()
        print(f"Generating Kyverno policy code with '{model}'")
        print("Prompt:", prompt)
        answer = call_llm(prompt, model=model, api_key=api_key, api_url=api_url)
        code = extract_code(answer, code_type="yaml")
        policy_file = policy_file.strip('"').strip("'").lstrip("{").rstrip("}")
        if not policy_file:
            policy_file = "policy.yaml"
        fpath = os.path.join(self.workdir, policy_file)
        with open(fpath, "w") as f:
            f.write(code)
        print("Code in answer:", code)

        tool_output = f"""The generated policy is below:
```yaml
{code}
```

This policy file has been saved at {fpath}.
"""
        return tool_output
