from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from app.notion_manager import NotionManager
from datetime import datetime
from typing import List, Optional
import os

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CharacterSettings(BaseModel):
    characterName: str
    mbti: str
    goals: Optional[str] = None
    preferences: Optional[str] = None
    notionApiKey: str
    notionPageUrl: str

class Activity(BaseModel):
    title: str
    startTime: str
    endTime: str
    thoughts: Optional[str] = None

class TimelineRequest(BaseModel):
    activities: List[Activity]

# Initialize managers
admin_notion = NotionManager(user_api_key=os.getenv("ADMIN_NOTION_TOKEN"))

@app.get("/")
async def read_root():
    return {
        "status": "ok", 
        "message": "Timeline App API is running"
    }

@app.post("/character/create")
async def create_character(settings: CharacterSettings):
    try:
        # 기존 사용자 확인
        existing_user = await admin_notion.get_user_data(settings.characterName)
        
        notion = NotionManager(settings.notionApiKey)
        page_id = notion.extract_page_id(settings.notionPageUrl)
        
        if existing_user:
            # 기존 사용자의 경우 설정 업데이트
            user_notion = NotionManager(existing_user["notion_api_key"])
            await user_notion.update_character(
                existing_user["database_ids"]["character_db_id"],
                settings.dict()
            )
            return {
                "status": "success",
                "message": "Character settings updated successfully",
                "data": {
                    "characterName": settings.characterName,
                    "mbti": settings.mbti,
                    "goals": settings.goals,
                    "preferences": settings.preferences
                }
            }
        else:
            # 새 사용자 생성
            databases = await notion.search_databases(page_id)
            await notion.save_character(
                databases["character_db_id"],
                settings.characterName,
                settings.mbti,
                settings.goals,
                settings.preferences
            )
            await notion.add_user_to_admin_db(settings.dict(), databases)
            return {
                "status": "success",
                "message": "Character created successfully",
                "data": {
                    "characterName": settings.characterName,
                    "mbti": settings.mbti,
                    "goals": settings.goals,
                    "preferences": settings.preferences,
                    "databases": databases
                }
            }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process request: {str(e)}")

@app.post("/timeline/generate/{character_name}")
async def generate_timeline(character_name: str, request: TimelineRequest):
    """활동 데이터를 받아서 타임라인과 일기 페이지를 생성"""
    try:
        print(f"Generating timeline for {character_name}")
        print(f"Received activities: {request.activities}")
        
        user_data = await admin_notion.get_user_data(character_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        print(f"Found user data: {user_data}")
        
        user_notion = NotionManager(user_data["notion_api_key"])
        
        # 타임라인과 일기 페이지 생성
        await user_notion.generate_daily_timeline(
            user_data["database_ids"]["diary_db_id"],
            datetime.now(),
            [activity.dict() for activity in request.activities]
        )
        
        return {
            "status": "success",
            "message": "타임라인과 일기 페이지가 생성되었습니다."
        }
    except Exception as e:
        print(f"Error generating timeline: {str(e)}")
        print(f"Full error details: ", e.__dict__)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/questions/generate/{character_name}")
async def generate_questions(character_name: str):
    """오늘 작성된 일기를 분석하여 성찰 질문 생성"""
    try:
        print(f"Generating questions for {character_name}")
        user_data = await admin_notion.get_user_data(character_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        print(f"Found user data: {user_data}")
        user_notion = NotionManager(user_data["notion_api_key"])
        
        # 캐릭터 정보 가져오기
        character_data = await user_notion.get_character_data(
            user_data["database_ids"]["character_db_id"]
        )
        
        if not character_data or not character_data.get("mbti"):
            raise HTTPException(status_code=400, detail="MBTI 정보가 필요합니다.")
        
        # 오늘 작성된 일기 가져오기
        today = datetime.now()
        journal_content = await user_notion.get_todays_journal(
            user_data["database_ids"]["diary_db_id"],
            today
        )
        
        print(f"Found journal content: {journal_content}")
        
        if not journal_content:
            raise HTTPException(
                status_code=400, 
                detail="오늘 작성된 일기가 없습니다. 먼저 일기를 작성해주세요."
            )
        
        # 성찰 질문 생성 및 저장
        question_page_id = await user_notion.generate_reflection_questions(
            user_data["database_ids"]["diary_db_id"],
            today,
            journal_content,
            character_data["mbti"],
            goals=character_data.get("goals"),
            preferences=character_data.get("preferences")
        )
        
        print(f"Generated questions page: {question_page_id}")
        
        return {
            "status": "success",
            "message": "성찰 질문이 생성되었습니다."
        }
    except Exception as e:
        print(f"Error generating questions: {str(e)}")
        print(f"Full error details: ", e.__dict__)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)