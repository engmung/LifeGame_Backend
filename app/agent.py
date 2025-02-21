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
    def __init__(self):
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
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
            system_prompt="""Gemini가 생성한 분석과 질문을 정리하여 노션 페이지에 적합한 형식으로 변환합니다.
            
            응답은 반드시 다음 JSON 형식으로만 출력해야 하며, 그 외의 설명이나 마크다운은 포함하지 않습니다:
            {"questions": ["질문1", "질문2", "질문3", "질문4", "질문5"]}"""
        )
        
        self.character_info = {
            'goals': None,
            'preferences': None
        }

    async def get_gemini_analysis(self, journal_content: str, mbti: str) -> ReasoningResult:
        """Gemini를 사용하여 일기 분석과 질문 생성"""
        prompt = f"""당신은 사용자의 MBTI, 목표, 선호도를 고려하여 일기를 분석하고 의미 있는 자기성찰 질문을 생성하는 전문가입니다.
        일기에서 드러나는 사고방식, 행동 패턴, 감정의 흐름을 파악하고, 사용자의 성장을 돕는 통찰력 있는 질문을 제시해주세요.
        
        사용자 정보:
        - MBTI: {mbti}
        - 목표: {self.character_info.get('goals', '정보 없음')}
        - 선호도: {self.character_info.get('preferences', '정보 없음')}
        
        분석과 질문 생성 시 다음 사항을 고려해주세요:
        1. MBTI 성향과의 연관성
        2. 감정과 사고의 패턴
        3. 행동과 결정의 동기
        4. 현재 상황과 장기 목표와의 관계
        5. 선호하는 학습/행동 방식과의 연관성
        6. 잠재적 고정관념이나 편향
        7. 성장 가능성과 개선점
        
        특히 다음 사항들을 분석에 반영해주세요:
        - 사용자의 목표(AI/자동화/블록체인 학습, 창업)와 현재 상황의 연관성
        - 자기주도적 학습 선호도와 현재 대처 방식의 관계
        - 실전 중심의 학습 스타일이 현재 상황에 어떻게 적용될 수 있는지
        
        분석과 질문을 다음과 같은 형식으로 작성해주세요:

        [분석]
        여기에 2-3문단의 분석을 작성해주세요.

        [질문]
        1. 첫 번째 질문
        2. 두 번째 질문
        ...
        (7-8개의 질문 작성)

        일기 내용:
        {journal_content}"""

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
            # 캐릭터 정보 업데이트
            self.character_info['goals'] = goals
            self.character_info['preferences'] = preferences
            
            # 1. Gemini로 분석 및 초기 질문 생성
            result = await self.get_gemini_analysis(journal_content, mbti)
            print(f"Gemini analysis: {result.analysis}")
            print(f"Gemini questions: {result.questions}")
            
            # 2. GPT-4o-mini로 질문 정제 및 포맷팅
            formatted = await self.formatter_agent.run(
                f"""Gemini가 생성한 다음 분석과 질문들을 5개의 명확하고 통찰력 있는 질문으로 정리해주세요.
                
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