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

from ciso_agent.llm import call_llm, extract_code
from ciso_agent.tools.utils import trim_quote
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class GenerateOPARegoToolInput(BaseModel):
    sentence: Union[str, dict] = Field(
        description="A short description of OPA Rego policy to be generated. This includes what is validated with the Rego policy evaluation."
    )
    policy_file: str = Field(description="A filepath for the Rego policy to be saved.")
    input_file: str = Field(description="The filepath to the input data to be used for checking the policy.")


class GenerateOPARegoTool(BaseTool):
    name: str = "GenerateOPARegoTool"
    # correct description
    description: str = "The tool to generate an OPA Rego policy. This tool returns the generated Rego policy."

    args_schema: type[BaseModel] = GenerateOPARegoToolInput

    # disable cache
    cache_function: Callable = lambda _args, _result: False

    workdir: str = ""

    def __init__(self, **kwargs):
        super_args = {k: v for k, v in kwargs.items() if k not in ["workdir"]}
        super().__init__(**super_args)
        if "workdir" in kwargs:
            self.workdir = kwargs["workdir"]

    def _run(self, sentence: Union[str, dict], policy_file: str, input_file: str) -> str:
        print("GenerateOPARegoTool is called")
        policy_file = trim_quote(policy_file)
        input_file = trim_quote(input_file)

        spec = sentence
        if isinstance(spec, dict):
            try:
                spec = json.dumps(spec, indent=2)
            except Exception:
                pass
        prompt = f"""Generate a very simple OPA Rego policy to evaluate the following condition:
    {spec}
"""
        if input_file:
            input_data = ""
            fpath = os.path.join(self.workdir, input_file)

            if not os.path.exists(fpath):
                raise OSError(f"input_file `{input_file}` is not found. This file must be prepared beforehand.")

            with open(fpath, "r") as f:
                input_data = f.read()

            truncated_msg = ""
            # truncate input_data to avoid too long input token
            if len(input_data) > 1000:
                input_data = input_data[:1000]
                truncated_msg = "\n(original data is too long, so truncated here)"
            prompt += f"""
Input data to be evaluated:
```json
{input_data}
{truncated_msg}
```
"""
        prompt += """

Points:
- `input` in your code is the above "Input data"
- If input data is just a string, check string match
- If input data is truncated, assume the data contents
- the final output must be `result`
- when input data should be disallowed, `result` must be `false`
- the package name must be `check`
- always insert `import rego.v1` after `package check`
- OPA is case sensitive. "False" and "false" is different.
- when error says "`if` keyword is required before rule body", you should change the code
  from something like `result := false {}` to `result := false if {}`
- The following is an example of a OPA Rego policy to disallow input if any item's value contains "ab"
```rego
package check
import rego.v1

default result := true

result := false if {
    some i
    contains(input.items[i].value, "ab")
}
```

for this example input data.
```json
{
    "items": [
        {"value": "abc"},
        {"value": "def"}
    ]
}
```
"""

        model = os.getenv("CODE_GEN_MODEL")
        api_key = os.getenv("CODE_GEN_API_KEY")
        print(f"Generating OPA Rego policy code with '{model}'")
        print("Prompt:", prompt)
        answer = call_llm(prompt, model=model, api_key=api_key)
        code = extract_code(answer, code_type="rego")
        policy_file = policy_file.strip('"').strip("'").lstrip("{").rstrip("}")
        if not policy_file:
            policy_file = "policy.rego"
        opath = os.path.join(self.workdir, policy_file)
        with open(opath, "w") as f:
            f.write(code)
        print("Code in answer:", code)

        tool_output = f"""The generated policy is below:
```rego
{code}
```

This policy file has been saved at {opath}.
"""
        return tool_output
