from pydantic import BaseModel
from typing import List
from pydantic_ai import Agent, RunContext
import json
import os

from pydantic import BaseModel
from typing import List
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
from openai import OpenAI
import os
import json

class ReasoningResult(BaseModel):
    title: str
    content: str

class Quest(BaseModel):
    title: str
    type: str  # "Main Quest" or "Sub Quest"
    description: str

class QuestResponse(BaseModel):
    quests: List[Quest]

class QuestGenerator:
    def __init__(self):
        self.deepseek_client = OpenAI(
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url="https://api.deepseek.com/v1"
        )
        
        self.gpt4_mini_model = OpenAIModel(
            "gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY")
        )
        
        self.quest_agent = Agent(
            self.gpt4_mini_model,
            deps_type=dict,
            result_type=QuestResponse,
            system_prompt="""분석을 바탕으로 퀘스트를 정리해주세요. 보상은 설명에 함께 넣어주세요. 메인퀘스트 2개, 서브퀘스트 2개로 정리해주세요.
            응답은 반드시 다음 JSON 형식으로만 출력해야 하며, 그 외의 설명이나 마크다운은 포함하지 않습니다:
            {"quests": [{"title": "퀘스트 제목", "type": "Main Quest|Sub Quest", "description": "설명"}]}"""
        )

        @self.quest_agent.system_prompt
        def add_mbti_context(ctx: RunContext[dict]) -> str:
            return f"""MBTI 유형 {ctx.deps['mbti']} 특성을 고려하여:
            - {ctx.deps['mbti'][:2]}: {'외향적인 활동' if 'E' in ctx.deps['mbti'] else '내면적 성장'}에 초점
            - {ctx.deps['mbti'][2:3]}: {'구체적이고 실제적인' if 'S' in ctx.deps['mbti'] else '추상적이고 창의적인'} 목표 강조
            - {ctx.deps['mbti'][3:4]}: {'논리적' if 'T' in ctx.deps['mbti'] else '감정적'} 측면 고려
            - {ctx.deps['mbti'][4:5]}: {'계획적' if 'J' in ctx.deps['mbti'] else '유연한'} 퀘스트 구성"""

    async def get_reasoning(self, mbti: str, goals: str, preferences: str) -> ReasoningResult:
        system_prompt = """당신은 사용자의 MBTI, 목표, 선호도를 분석하여 4개의 단기 퀘스트를 제안하는 전문가입니다.
        사용자의 성향과 목표를 통합적으로 분석하고, 맞춤 퀘스트를 만들어주세요. 퀘스트는 하루 1~2시간 내에 완료할 수 있어야 합니다.
        퀘스트는 공부, 프로젝트, 산책, 독서와 같은 활동의 느낌의 실용적인 내용으로 구성해주세요. 가상의 뱃지나 칭호를 주는 등 재미있는 보상도 넣어주세요."""
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"""다음 사용자 정보를 바탕으로 분석해주세요:
            - MBTI: {mbti}
            - 목표: {goals}
            - 선호도: {preferences}"""}
        ]
        
        response = self.deepseek_client.chat.completions.create(
            model="deepseek-reasoner",
            messages=messages
        )
        
        content = response.choices[0].message.content
        return ReasoningResult(
            title="사용자 분석 결과",
            content=content
        )

    async def generate_quests(self, mbti: str, goals: str, preferences: str) -> List[Quest]:
        try:
            # 1. Get reasoning from DeepSeek
            reasoning = await self.get_reasoning(mbti, goals, preferences)
            print(f"Reasoning result: {reasoning.content}")
            
            # 2. Generate quests based on reasoning
            result = await self.quest_agent.run(
                f"""다음 분석 결과를 바탕으로 하루 1~2시간 내에 완료할 수 있는 간단한 퀘스트를 생성해주세요:
                {reasoning.content}""",
                deps={
                    "mbti": mbti,
                    "goals": goals,
                    "preferences": preferences
                }
            )
            
            return result.data.quests
            
        except Exception as e:
            print(f"Error generating quests: {str(e)}")
            raise


class Activity(BaseModel):
    name: str
    start: str
    end: str
    duration: int
    review: str

class DailyInsightGenerator:
    def __init__(self):
        self.agent = Agent(
            "gpt-4o-mini",
            system_prompt="""당신은 사용자의 하루 활동을 분석하고 인사이트를 제공하는 전문가입니다.

            응답은 반드시 다음과 같은 JSON 형식이어야 합니다:
            {
                "summary": "하루 전체 요약 (1-2문장)",
                "patterns": ["발견된 주요 패턴 1", "패턴 2"],
                "insights": ["주요 인사이트 1", "인사이트 2"],
                "suggestions": ["개선 제안 1", "제안 2"]
            }
            """
        )

    async def analyze_daily_activities(self, activities: List[Activity], mbti: str = None) -> dict:
        try:
            activities_json = [
                {
                    "name": a.name,
                    "start": a.start,
                    "end": a.end,
                    "duration": a.duration,
                    "review": a.review
                } for a in activities
            ]

            prompt = f"""다음 활동 데이터를 분석하여 JSON 형식으로만 응답해주세요:

활동: {json.dumps(activities_json, ensure_ascii=False)}
MBTI: {mbti if mbti else '정보 없음'}

분석 관점:
1. 시간대별 활동 패턴
2. 활동 시간 분포
3. 집중도와 휴식 패턴
4. 활동 카테고리
5. MBTI 성향 연관성"""

            result = await self.agent.run(prompt)
            return json.loads(result.data if isinstance(result.data, str) else json.dumps(result.data))
            
        except Exception as e:
            print(f"Error analyzing activities: {str(e)}")
            raise