from pydantic import BaseModel
from typing import List
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIModel
import google.generativeai as genai
import os
import json

class ReasoningResult(BaseModel):
    analysis: str
    questions: List[str]

class QuestionsResponse(BaseModel):
    questions: List[str]

class ReflectionAnalyzer:
    def __init__(self, gemini_api_key: str = None):
        if not gemini_api_key:
            raise ValueError("Gemini API key is required")
            
        genai.configure(api_key=gemini_api_key)
        self.generation_config = {
            "temperature": 0.7,
            "top_p": 0.95,
            "top_k": 64,
            "max_output_tokens": 65536,
            "response_mime_type": "text/plain",
        }
        self.model = genai.GenerativeModel(
            model_name="gemini-2.0-flash-thinking-exp-01-21",
            generation_config=self.generation_config,
        )
        
        self.gpt4_mini_model = OpenAIModel(
            "gpt-4o-mini",
            api_key=os.getenv("OPENAI_API_KEY")
        )
        
        self.formatter_agent = Agent(
            self.gpt4_mini_model,
            deps_type=dict,
            result_type=QuestionsResponse,
            system_prompt="""Gemini가 생성한 분석과 질문들을 검토하여, 가장 통찰력 있고 깊이 있는 질문 5개를 선택하고 정제하여 제시합니다.
            선택 기준:
            1. 구체적이고 명확한 질문
            2. 깊은 자기성찰을 유도하는 질문
            3. 감정, 행동, 가치관을 균형있게 다루는 질문
            4. MBTI 특성을 고려한 질문
            5. 사용자의 목표와 선호도를 반영한 질문
            
            응답은 반드시 다음 JSON 형식으로만 출력해야 하며, 정확히 5개의 질문이어야 합니다:
            {"questions": ["질문1", "질문2", "질문3", "질문4", "질문5"]}"""
        )
        
        self.user_info = {
            'goals': None,
            'preferences': None
        }

    async def get_gemini_analysis(self, journal_data: dict, mbti: str) -> ReasoningResult:
        """Gemini를 사용하여 활동 기록과 일기를 분석하고 성찰 질문 생성"""
        
        # 타임라인 데이터를 문자열로 변환
        timeline_text = ""
        for activity in journal_data["timeline"]:
            timeline_text += f"\n시간: {activity['time']}"
            timeline_text += f"\n활동: {activity['activity']}"
            if 'thoughts' in activity:
                timeline_text += f"\n생각/감정: {activity['thoughts']}"
            timeline_text += "\n"

        prompt = f"""당신은 사용자의 하루 활동과 일기를 깊이있게 이해하고, 의미 있는 자기성찰을 돕는 전문가입니다.
        객관적인 활동 기록과 순간의 감정, 그리고 하루를 정리한 일기를 모두 고려하여 사용자의 더 깊은 자기이해를 돕는 분석과 질문을 제시해주세요.
        
        사용자 정보:
        - MBTI: {mbti}
        - 목표: {self.user_info.get('goals', '정보 없음')}
        - 선호도: {self.user_info.get('preferences', '정보 없음')}
        
        다음 관점들을 고려하여 분석과 5개의 질문을 생성해주세요:
        1. 순간의 감정과 회고 시점의 감정 차이
        2. 활동과 감정의 연관성
        3. 하루 동안의 감정/생각 변화 패턴
        4. 현재 상황과 장기 목표의 연결점
        5. 사용자의 행동 패턴과 동기
        6. 잠재된 고정관념이나 편향된 시각
        7. MBTI 특성과 관련된 통찰
        8. 선호하는 학습/행동 방식의 효과성
        
        === 하루 활동 타임라인 ===
        {timeline_text}

        === 일기 내용 ===
        {journal_data["journal"]}

        분석과 질문을 다음과 같은 형식으로 작성해주세요:

        [분석]
        여기에 2-3문단의 분석을 작성해주세요.

        [질문]
        1. 첫 번째 질문
        2. 두 번째 질문
        ..."""

        chat = self.model.start_chat()
        response = chat.send_message(prompt)
        content = response.text
        
        # 분석과 질문 부분 분리
        try:
            parts = content.split('[질문]')
            analysis = parts[0].replace('[분석]', '').strip()
            questions_text = parts[1].strip()
            
            questions = []
            for line in questions_text.split('\n'):
                line = line.strip()
                if line and '.' in line:
                    question = line.split('.', 1)[1].strip()
                    questions.append(question)
        except Exception as e:
            print(f"Error parsing Gemini response: {str(e)}")
            print(f"Raw response: {content}")
            analysis = content
            questions = []
        
        return ReasoningResult(
            analysis=analysis,
            questions=questions
        )

    async def generate_questions(self, journal_content: str, mbti: str, goals: str = None, preferences: str = None) -> List[str]:
        try:
            # 사용자 정보 업데이트
            self.user_info['goals'] = goals
            self.user_info['preferences'] = preferences
            
            # 1. Gemini로 분석 및 초기 질문 생성
            result = await self.get_gemini_analysis(journal_content, mbti)
            print(f"Gemini questions generated: {len(result.questions)} questions")
            
            # 2. GPT-4o-mini로 질문 정제 및 포맷팅
            formatted = await self.formatter_agent.run(
                f"""다음 분석과 질문들을 검토하여 가장 통찰력 있는 5개의 질문을 선택하고 정제해주세요.

분석 내용:
{result.analysis}

생성된 질문들:
{json.dumps(result.questions, ensure_ascii=False, indent=2)}""",
                deps={"mbti": mbti}
            )
            
            return formatted.data.questions
            
        except Exception as e:
            print(f"Error in generate_questions: {str(e)}")
            return [
                "오늘 하루 동안 가장 강하게 느낀 감정은 무엇이었나요? 그 감정이 들었던 이유는 무엇일까요?",
                "오늘의 경험 중에서 자신에 대해 새롭게 알게 된 점이 있다면 무엇인가요?",
                "오늘 했던 선택들 중에서 다르게 할 수 있었던 것이 있었나요?",
                "오늘 하루를 통해 자신의 어떤 가치관이나 신념이 확인되었나요?",
                "내일의 자신에게 해주고 싶은 이야기가 있다면 무엇인가요?"
            ]