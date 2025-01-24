from pydantic import BaseModel
from typing import List
from pydantic_ai import Agent, RunContext
import json
import os

class Quest(BaseModel):
    title: str
    type: str  # "Main Quest" or "Sub Quest"
    description: str

class Activity(BaseModel):
    name: str
    start: str
    end: str
    duration: int
    review: str

class QuestGenerator:
    def __init__(self):
        self.agent = Agent(
            "gpt-4o-mini",
            deps_type=dict,
            system_prompt="""당신은 사용자의 특성을 기반으로 매력적인 퀘스트를 생성하는 전문가입니다.
            응답은 반드시 JSON 형식으로만 출력해야 하며, 그 외의 설명이나 마크다운은 포함하지 않습니다."""
        )
        
        @self.agent.system_prompt
        def add_mbti_context(ctx: RunContext[dict]) -> str:
            return f"""MBTI 유형 {ctx.deps['mbti']} 특성을 고려하여:
            - {ctx.deps['mbti'][:2]}: {'외향적인 활동' if 'E' in ctx.deps['mbti'] else '내면적 성장'}에 초점
            - {ctx.deps['mbti'][2:3]}: {'구체적이고 실제적인' if 'S' in ctx.deps['mbti'] else '추상적이고 창의적인'} 목표 강조
            - {ctx.deps['mbti'][3:4]}: {'논리적' if 'T' in ctx.deps['mbti'] else '감정적'} 측면 고려
            - {ctx.deps['mbti'][4:5]}: {'계획적' if 'J' in ctx.deps['mbti'] else '유연한'} 퀘스트 구성"""

        @self.agent.system_prompt
        def add_quest_rules() -> str:
            return """다음 규칙에 따라 퀘스트를 생성하세요:
            1. 정확히 1개의 메인 퀘스트와 2-3개의 서브 퀘스트 생성
            2. 각 퀘스트는 현실적이고 달성 가능해야 함
            3. 메인 퀘스트는 주요 목표와 연계
            4. 서브 퀘스트는 메인 퀘스트를 지원하는 형태
            5. 설명은 명확하고 간단하게

            다음 JSON 형식으로만 출력하세요:
            [{"title": "퀘스트 제목", "type": "Main Quest", "description": "설명"}, {"title": "퀘스트 제목", "type": "Sub Quest", "description": "설명"}]"""
    
    async def generate_quests(self, mbti: str, goals: str, preferences: str) -> List[Quest]:
        try:
            prompt = f"""다음 사용자를 위한 퀘스트 JSON 데이터만 생성해주세요:
            MBTI: {mbti}
            목표: {goals if goals else "특별히 설정된 목표 없음"}
            선호도: {preferences if preferences else "특별히 설정된 선호도 없음"}"""

            result = await self.agent.run(
                prompt,
                deps={
                    "mbti": mbti,
                    "goals": goals,
                    "preferences": preferences
                }
            )
            
            print("Raw AI Response:", result.data)
            quest_data = result.data if isinstance(result.data, list) else json.loads(result.data)
            print("Parsed quest data:", quest_data)
            return [Quest(**quest) for quest in quest_data]
            
        except Exception as e:
            print(f"Error generating quests: {str(e)}")
            raise

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