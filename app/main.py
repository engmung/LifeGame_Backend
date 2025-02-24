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
origins = [
    "https://lifegamedev.vercel.app",  # Production frontend
    "http://localhost:3000",           # Local development frontend
    "http://localhost:5173",           # Vite default development port
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class UserSettings(BaseModel):
    characterName: str
    mbti: str
    goals: Optional[str] = None
    preferences: Optional[str] = None
    notionApiKey: str
    notionPageUrl: str
    geminiApiKey: str
    confirmUpdate: Optional[bool] = None

class Activity(BaseModel):
    title: str
    startTime: str
    endTime: str
    thoughts: Optional[str] = None

class TimelineRequest(BaseModel):
    activities: List[Activity]

# Initialize NotionManager with admin token
admin_notion = NotionManager(user_api_key=os.getenv("ADMIN_NOTION_TOKEN"))

@app.get("/")
async def read_root():
    return {
        "status": "ok", 
        "message": "Timeline App API is running"
    }

@app.post("/user/check")
async def check_user(settings: UserSettings):
    """사용자 이름이 이미 존재하는지 확인"""
    try:
        existing_user = await admin_notion.get_user_data(settings.characterName)
        if existing_user:
            return {
                "status": "exists",
                "message": "이미 등록된 사용자 이름입니다. 업데이트하시겠습니까?",
                "data": {
                    "characterName": settings.characterName,
                    "notionUrl": existing_user.get("notion_url")
                }
            }
        return {
            "status": "new",
            "message": "새로운 사용자로 등록됩니다."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/user/create")
async def create_user(settings: UserSettings):
    try:
        # 기존 사용자 확인
        existing_user = await admin_notion.get_user_data(settings.characterName)
        
        if existing_user:
            if settings.confirmUpdate is not True:
                return {
                    "status": "confirmation_required",
                    "message": "이미 등록된 사용자 이름입니다. 업데이트하시겠습니까?",
                    "data": {
                        "characterName": settings.characterName,
                        "notionUrl": existing_user.get("notion_url")
                    }
                }
            
            # 사용자가 업데이트를 확인한 경우
            user_notion = NotionManager(
                user_api_key=existing_user["notion_api_key"],
                gemini_api_key=existing_user["gemini_api_key"]
            )
            
            # Character DB에서 MBTI, 목표, 선호도만 업데이트
            await user_notion.update_character_info(
                existing_user["database_ids"]["character_db_id"],
                settings.characterName,
                settings.mbti,
                settings.goals,
                settings.preferences
            )
            
            return {
                "status": "success",
                "message": "User settings updated successfully",
                "data": {
                    "characterName": settings.characterName,
                    "mbti": settings.mbti,
                    "goals": settings.goals,
                    "preferences": settings.preferences,
                    "notionPageUrl": existing_user.get("notion_url")
                }
            }
        else:
            # 새 사용자 생성 (기존 로직)
            notion = NotionManager(settings.notionApiKey)
            page_id = notion.extract_page_id(settings.notionPageUrl)
            databases = await notion.search_databases(page_id)
            
            await notion.save_user(
                databases["character_db_id"],
                settings.characterName,
                settings.mbti,
                settings.goals,
                settings.preferences
            )
            await notion.add_user_to_admin_db(settings.dict(), databases)
            
            return {
                "status": "success",
                "message": "User created successfully",
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

@app.post("/timeline/generate/{user_name}")
async def generate_timeline(user_name: str, request: TimelineRequest):
    """활동 데이터를 받아서 타임라인과 일기 페이지를 생성"""
    try:
        print(f"Generating timeline for {user_name}")
        print(f"Received activities: {request.activities}")
        
        user_data = await admin_notion.get_user_data(user_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        print(f"Found user data: {user_data}")
        
        user_notion = NotionManager(
            user_api_key=user_data["notion_api_key"],
            gemini_api_key=user_data["gemini_api_key"]
        )
        
        # 타임라인과 일기 페이지 생성
        await user_notion.generate_daily_timeline(
            user_data["database_ids"]["diary_db_id"],
            datetime.now(),
            [activity.dict() for activity in request.activities]
        )
        
        return {
            "status": "success",
            "message": "타임라인과 일기 페이지가 생성되었습니다.",
            "notionPageUrl": user_data.get("notion_url")
        }
    except Exception as e:
        print(f"Error generating timeline: {str(e)}")
        print(f"Full error details: ", e.__dict__)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/questions/generate/{user_name}")
async def generate_questions(user_name: str):
    """오늘 작성된 일기를 분석하여 성찰 질문 생성"""
    try:
        print(f"Generating questions for {user_name}")
        user_data = await admin_notion.get_user_data(user_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        print(f"Found user data: {user_data}")
        user_notion = NotionManager(
            user_api_key=user_data["notion_api_key"],
            gemini_api_key=user_data["gemini_api_key"]
        )
        
        # 사용자 정보 가져오기
        user_info = await user_notion.get_user_info(
            user_data["database_ids"]["character_db_id"]
        )
        
        if not user_info or not user_info.get("mbti"):
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
            user_info["mbti"],
            goals=user_info.get("goals"),
            preferences=user_info.get("preferences")
        )
        
        print(f"Generated questions page: {question_page_id}")
        
        return {
            "status": "success",
            "message": "성찰 질문이 생성되었습니다.",
            "notionPageUrl": user_data.get("notion_url")
        }
    except Exception as e:
        print(f"Error generating questions: {str(e)}")
        print(f"Full error details: ", e.__dict__)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user/{user_name}")
async def get_user(user_name: str):
    """사용자 정보 조회"""
    try:
        user_data = await admin_notion.get_user_data(user_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
            
        # API 키는 제외하고 필요한 정보만 반환
        return {
            "status": "success",
            "data": {
                "notionUrl": user_data.get("notion_url"),
                "databaseIds": user_data.get("database_ids", {})
            }
        }
    except Exception as e:
        print(f"Error getting user data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)