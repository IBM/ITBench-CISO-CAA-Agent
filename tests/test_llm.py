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

from ciso_agent.llm import init_agent_llm

from dotenv import load_dotenv

load_dotenv()


def agent_llm():
    llm = init_agent_llm()

    prompt = "Why is the sky blue?"

    print("=" * 90)
    print(" # Prompt ")
    print("=" * 90)
    print(prompt)
    answer = llm.call(
        [
            {
                "role": "user",
                "content": prompt,
            },
        ]
    )
    print("")
    print("=" * 90)
    print(" # Answer ")
    print("=" * 90)
    print(answer)


if __name__ == "__main__":
    agent_llm()
