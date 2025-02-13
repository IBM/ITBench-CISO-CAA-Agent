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

import pytest
import os
from crewai import Agent, Task, Crew, Process, LLM
from crewai.crews.crew_output import CrewOutput
from dotenv import load_dotenv


load_dotenv()


def ask_model_name_with_agent(llm: any=None) -> CrewOutput:
    test_agent = Agent(
        role="Test",
        goal=f"Answer to the question",
        backstory="",
        verbose=True,
        llm=llm,
    )

    test_task = Task(
        name="test_task",
        description="Say your model name",
        expected_output="your model name",
        agent=test_agent,
    )

    crew = Crew(
        name="Test Crew",
        agents=[test_agent],
        tasks=[test_task],
        process=Process.sequential,
        verbose=True,
    )
    crew_output = crew.kickoff()
    return crew_output


def test_agent_with_gpt():
    llm = LLM(model="gpt-4o-mini", api_key=os.getenv("OPENAI_API_KEY"))
    crew_output = ask_model_name_with_agent(llm=llm)
    assert isinstance(crew_output, CrewOutput)
    answer = crew_output.raw
    assert answer
    assert isinstance(answer, str)
    assert "gpt" in answer.lower()


def test_agent_with_llama_by_ollama():
    llm = LLM(model="ollama/llama3.2", base_url="http://localhost:11434")
    crew_output = ask_model_name_with_agent(llm=llm)
    assert isinstance(crew_output, CrewOutput)
    answer = crew_output.raw
    assert answer
    assert isinstance(answer, str)
    assert "llama" in answer.lower()
