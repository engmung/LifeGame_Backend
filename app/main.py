from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from app.notion_manager import NotionManager
from datetime import datetime
from typing import List, Optional, Dict, Any
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
            # API 키 업데이트된 것 적용
            updated_notion_api_key = settings.notionApiKey or existing_user["notion_api_key"]
            updated_gemini_api_key = settings.geminiApiKey or existing_user["gemini_api_key"]
            
            user_notion = NotionManager(
                user_api_key=updated_notion_api_key,
                gemini_api_key=updated_gemini_api_key
            )
            
            # Character DB에서 MBTI, 목표, 선호도만 업데이트
            await user_notion.update_character_info(
                existing_user["database_ids"]["character_db_id"],
                settings.characterName,
                settings.mbti,
                settings.goals,
                settings.preferences
            )
            
            # 관리자 DB의 API 키 정보 업데이트
            blocks = admin_notion.admin_client.blocks.children.list(existing_user["id"])
            
            for block in blocks["results"]:
                if block["type"] == "paragraph" and block["paragraph"]["rich_text"]:
                    text = block["paragraph"]["rich_text"][0]["text"]["content"]
                    
                    # Notion API Key 업데이트
                    if text.startswith("Notion API Key:") and settings.notionApiKey:
                        admin_notion.admin_client.blocks.update(
                            block_id=block["id"],
                            paragraph={
                                "rich_text": [{
                                    "text": {"content": f"Notion API Key: {settings.notionApiKey}"}
                                }]
                            }
                        )
                    
                    # Gemini API Key 업데이트
                    elif text.startswith("Gemini API Key:") and settings.geminiApiKey:
                        admin_notion.admin_client.blocks.update(
                            block_id=block["id"],
                            paragraph={
                                "rich_text": [{
                                    "text": {"content": f"Gemini API Key: {settings.geminiApiKey}"}
                                }]
                            }
                        )
            
            # 사용자 업데이트 로그 기록
            update_details = f"MBTI: {settings.mbti}\n"
            if settings.goals:
                update_details += f"목표: {settings.goals}\n"
            if settings.preferences:
                update_details += f"선호도: {settings.preferences}\n"
            if settings.notionApiKey:
                update_details += "Notion API Key: 업데이트됨\n"
            if settings.geminiApiKey:
                update_details += "Gemini API Key: 업데이트됨\n"
            
            await admin_notion.log_activity(
                settings.characterName,
                "User Update",
                "Success",
                update_details
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
            
            try:
                databases = await notion.search_databases(page_id)
            except Exception as db_error:
                error_message = str(db_error)
                if "Could not find block with ID" in error_message and "Make sure the relevant pages and databases are shared with your integration" in error_message:
                    error_message = "노션 페이지와 통합(integration)이 공유되지 않았습니다. 노션 페이지에서 '공유' 버튼을 클릭하고 만든 통합을 초대해주세요."
                
                await admin_notion.log_activity(
                    settings.characterName,
                    "User Creation",
                    "Error",
                    error_message
                )
                raise ValueError(error_message)
            
            await notion.save_user(
                databases["character_db_id"],
                settings.characterName,
                settings.mbti,
                settings.goals,
                settings.preferences
            )
            await notion.add_user_to_admin_db(settings.dict(), databases)
            
            # 사용자 생성 로그 기록
            creation_details = f"MBTI: {settings.mbti}\n"
            if settings.goals:
                creation_details += f"목표: {settings.goals}\n"
            if settings.preferences:
                creation_details += f"선호도: {settings.preferences}\n"
            creation_details += f"Notion Page URL: {settings.notionPageUrl}\n"
            
            await admin_notion.log_activity(
                settings.characterName,
                "User Creation",
                "Success",
                creation_details
            )
            
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
        error_message = str(ve)
        await admin_notion.log_activity(
            settings.characterName,
            "User Creation",
            "Error",
            error_message
        )
        raise HTTPException(status_code=400, detail=error_message)
    except Exception as e:
        error_message = str(e)
        print("Error:", error_message)
        
        await admin_notion.log_activity(
            settings.characterName,
            "User Creation/Update",
            "Error",
            error_message
        )
        
        raise HTTPException(status_code=500, detail=f"Failed to process request: {error_message}")

@app.post("/timeline/generate/{user_name}")
async def generate_timeline(user_name: str, request: TimelineRequest):
    """활동 데이터를 받아서 타임라인과 일기 페이지를 생성"""
    try:
        print(f"Generating timeline for {user_name}")
        print(f"Received activities: {request.activities}")
        
        user_data = await admin_notion.get_user_data(user_name)
        if not user_data:
            await admin_notion.log_activity(
                user_name, 
                "Timeline Generation", 
                "Error", 
                "User not found"
            )
            raise HTTPException(status_code=404, detail="User not found")
        
        # 사용자 상태 확인
        if user_data.get("status") != "Active":
            await admin_notion.log_activity(
                user_name, 
                "Timeline Generation", 
                "Error", 
                "User account is not active"
            )
            raise HTTPException(
                status_code=403, 
                detail="User account is not active. Please wait for admin approval."
            )
        
        print(f"Found user data: {user_data}")
        
        user_notion = NotionManager(
            user_api_key=user_data["notion_api_key"],
            gemini_api_key=user_data["gemini_api_key"]
        )
        
        # 로그에 기록할 활동 데이터 요약
        activity_summary = f"활동 개수: {len(request.activities)}\n"
        activity_summary += "활동 목록:\n"
        for idx, activity in enumerate(request.activities, 1):
            activity_summary += f"{idx}. {activity.title} ({activity.startTime} - {activity.endTime})\n"
        
        # 타임라인과 일기 페이지 생성
        await user_notion.generate_daily_timeline(
            user_data["database_ids"]["diary_db_id"],
            datetime.now(),
            [activity.dict() for activity in request.activities]
        )
        
        # 성공 로그 기록
        await admin_notion.log_activity(
            user_name,
            "Timeline Generation",
            "Success",
            activity_summary
        )
        
        return {
            "status": "success",
            "message": "타임라인과 일기 페이지가 생성되었습니다.",
            "notionPageUrl": user_data.get("notion_url")
        }
    except Exception as e:
        error_message = str(e)
        print(f"Error generating timeline: {error_message}")
        print(f"Full error details: ", e.__dict__)
        
        # 에러 로그 기록
        await admin_notion.log_activity(
            user_name,
            "Timeline Generation",
            "Error",
            error_message
        )
        
        raise HTTPException(status_code=500, detail=error_message)

@app.post("/questions/generate/{user_name}")
async def generate_questions(user_name: str):
    """오늘 작성된 일기를 분석하여 성찰 질문 생성"""
    try:
        print(f"Generating questions for {user_name}")
        user_data = await admin_notion.get_user_data(user_name)
        if not user_data:
            await admin_notion.log_activity(
                user_name, 
                "Question Generation", 
                "Error", 
                "User not found"
            )
            raise HTTPException(status_code=404, detail="User not found")

        # 사용자 상태 확인
        if user_data.get("status") != "Active":
            await admin_notion.log_activity(
                user_name, 
                "Question Generation", 
                "Error", 
                "User account is not active"
            )
            raise HTTPException(
                status_code=403, 
                detail="User account is not active. Please wait for admin approval."
            )

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
            await admin_notion.log_activity(
                user_name, 
                "Question Generation", 
                "Error", 
                "MBTI 정보가 필요합니다"
            )
            raise HTTPException(status_code=400, detail="MBTI 정보가 필요합니다.")
        
        # 오늘 작성된 일기 가져오기
        today = datetime.now()
        journal_content = await user_notion.get_todays_journal(
            user_data["database_ids"]["diary_db_id"],
            today
        )
        
        print(f"Found journal content: {journal_content}")
        
        if not journal_content:
            await admin_notion.log_activity(
                user_name, 
                "Question Generation", 
                "Error", 
                "오늘 작성된 일기가 없습니다"
            )
            raise HTTPException(
                status_code=400, 
                detail="오늘 작성된 일기가 없습니다. 먼저 일기를 작성해주세요."
            )
        
        # 성찰 질문 생성
        generated_questions = await user_notion.reflection_analyzer.generate_questions(
            journal_content=journal_content,
            mbti=user_info["mbti"],
            goals=user_info.get("goals"),
            preferences=user_info.get("preferences")
        )
        
        # 질문 페이지 저장
        question_page_id = await user_notion.generate_reflection_questions(
            user_data["database_ids"]["diary_db_id"],
            today,
            journal_content,
            user_info["mbti"],
            goals=user_info.get("goals"),
            preferences=user_info.get("preferences"),
            questions=generated_questions  # 생성된 질문 전달
        )
        
        print(f"Generated questions page: {question_page_id}")
        
        # 성공 로그 기록 - 생성된 질문 포함
        log_details = f"MBTI: {user_info['mbti']}\n"
        if user_info.get("goals"):
            log_details += f"목표: {user_info['goals']}\n"
        if user_info.get("preferences"):
            log_details += f"선호도: {user_info['preferences']}\n"
        log_details += f"일기 길이: {len(journal_content.get('journal', ''))}\n\n"
        
        # 생성된 질문 추가
        log_details += "생성된 질문:\n"
        for idx, question in enumerate(generated_questions, 1):
            log_details += f"{idx}. {question}\n"
        
        await admin_notion.log_activity(
            user_name,
            "Question Generation",
            "Success",
            log_details
        )
        
        return {
            "status": "success",
            "message": "성찰 질문이 생성되었습니다.",
            "notionPageUrl": user_data.get("notion_url")
        }
    except Exception as e:
        error_message = str(e)
        print(f"Error generating questions: {error_message}")
        print(f"Full error details: ", e.__dict__)
        
        # 에러 로그 기록
        await admin_notion.log_activity(
            user_name,
            "Question Generation",
            "Error",
            error_message
        )
        
        raise HTTPException(status_code=500, detail=error_message)

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
                "databaseIds": user_data.get("database_ids", {}),
                "status": user_data.get("status", "Inactive")
            }
        }
    except Exception as e:
        print(f"Error getting user data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

# 사용자 상태 확인 엔드포인트 추가
@app.get("/user/status/{user_name}")
async def get_user_status(user_name: str):
    """사용자 상태 조회"""
    try:
        user_data = await admin_notion.get_user_data(user_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
            
        return {
            "status": "success",
            "data": {
                "status": user_data.get("status", "Inactive")
            }
        }
    except Exception as e:
        print(f"Error getting user status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)