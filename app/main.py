from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from app.notion_manager import NotionManager
from app.agent import QuestGenerator
from datetime import datetime, timedelta
import asyncio
import argparse
import os

# 글로벌 설정
QUEST_CHECK_INTERVAL = 3600  # 초 단위 (테스트용 10초, 실제 운영시 3600초)
MIN_QUEST_COUNT = 2  # 이 개수 이하일 때 새 퀘스트 생성

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
    notionApiKey: str
    notionPageUrl: str

class QuestGenerateRequest(BaseModel):
    mbti: str
    goals: str
    preferences: str

class DailyWrapUpRequest(BaseModel):
    date: str

# Initialize managers
quest_generator = QuestGenerator()
admin_notion = NotionManager(user_api_key=os.getenv("ADMIN_NOTION_TOKEN"))

async def generate_quests_for_user(character_name: str):
    """Generate quests for a specific user and save to their Quest DB"""
    try:
        print(f"Generating quests for user: {character_name}")
        
        # Get user data from admin DB
        user_data = await admin_notion.get_user_data(character_name)
        if not user_data:
            raise ValueError(f"User {character_name} not found")
            
        print("User data retrieved:", user_data)
        
        # Initialize user's notion client
        user_notion = NotionManager(user_data["notion_api_key"])
        
        # Get user's character data
        character_data = await user_notion.get_character_data(user_data["database_ids"]["character_db_id"])
        print("Character data retrieved:", character_data)
        
        # Generate quests using AI
        quests = await quest_generator.generate_quests(
            mbti=character_data["mbti"],
            goals=character_data.get("goals", ""),
            preferences=character_data.get("preferences", "")
        )
        print(f"Generated {len(quests)} quests")
        
        # Save quests to user's Quest DB
        quest_db_id = user_data["database_ids"]["quest_db_id"]
        for quest in quests:
            await user_notion.save_quest(quest_db_id, quest)
            print(f"Saved quest: {quest.title}")
        
        # Update last quest generation time in admin DB
        await admin_notion.update_last_quest_generated(character_name)
        print("Updated last quest generation time")
        
        return {
            "status": "success",
            "message": f"Generated and saved {len(quests)} quests for {character_name}"
        }
        
    except Exception as e:
        print(f"Error generating quests: {str(e)}")
        return {
            "status": "error",
            "message": str(e)
        }

async def check_and_generate_quests():
    """Active 상태인 모든 유저의 퀘스트를 체크하고 필요시 생성"""
    try:
        # 관리자 DB에서 active 유저 조회
        response = admin_notion.client.databases.query(
            database_id=admin_notion.users_db_id,
            filter={"property": "Status", "select": {"equals": "Active"}}
        )

        for user in response["results"]:
            character_name = user["properties"]["Name"]["title"][0]["text"]["content"]
            user_data = await admin_notion.get_user_data(character_name)
            
            if not user_data:
                continue

            # 유저의 노션 클라이언트로 현재 퀘스트 수 확인
            user_notion = NotionManager(user_data["notion_api_key"])
            current_quests = await user_notion.get_active_quests(user_data["database_ids"]["quest_db_id"])
            
            # 퀘스트가 MIN_QUEST_COUNT개 이하면 새로운 퀘스트 생성
            if len(current_quests) <= MIN_QUEST_COUNT:
                print(f"Generating new quests for {character_name}")
                await generate_quests_for_user(character_name)
            
    except Exception as e:
        print(f"Error in check_and_generate_quests: {str(e)}")

async def periodic_quest_check():
    """주기적으로 퀘스트 체크 및 생성"""
    while True:
        print(f"Running periodic quest check (Interval: {QUEST_CHECK_INTERVAL}s)")
        await check_and_generate_quests()
        await asyncio.sleep(QUEST_CHECK_INTERVAL)

@app.on_event("startup")
async def start_scheduler():
    """서버 시작 시 자동으로 스케줄러 시작"""
    asyncio.create_task(periodic_quest_check())

# CLI command handler
async def handle_cli_command():
    parser = argparse.ArgumentParser(description='Quest generation CLI')
    parser.add_argument('--user', type=str, help='Character name to generate quests for')
    args = parser.parse_args()
    
    if args.user:
        result = await generate_quests_for_user(args.user)
        print(result)
    else:
        print("Please provide a user name with --user argument")

# API endpoints
@app.get("/")
async def read_root():
    return {
        "status": "ok", 
        "message": "Quest App API is running",
        "quest_check_interval": QUEST_CHECK_INTERVAL,
        "min_quest_count": MIN_QUEST_COUNT
    }

@app.get("/quests/{character_name}")
async def get_user_quests(character_name: str):
    """사용자의 현재 활성화된 퀘스트들을 조회"""
    try:
        user_data = await admin_notion.get_user_data(character_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        user_notion = NotionManager(user_data["notion_api_key"])
        quests = await user_notion.get_active_quests(user_data["database_ids"]["quest_db_id"])
        
        return {
            "status": "success",
            "data": quests
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/quests/complete/{character_name}")
async def complete_quest(character_name: str, quest_data: dict):
    """퀘스트 완료 처리 및 활동 로그 저장"""
    try:
        user_data = await admin_notion.get_user_data(character_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        user_notion = NotionManager(user_data["notion_api_key"])
        
        # 활동 로그 저장
        await user_notion.save_activity_log(
            user_data["database_ids"]["activity_db_id"],
            quest_data["title"],
            quest_data["timerDetails"],
            quest_data["review"]
        )
        
        # 퀘스트 완료 처리
        await user_notion.complete_quest(
            user_data["database_ids"]["quest_db_id"], 
            quest_data["id"]
        )
        
        return {
            "status": "success",
            "message": "Quest completed and activity logged"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/character/create")
async def create_character(settings: CharacterSettings):
    """새 캐릭터 생성 및 설정"""
    try:
        notion = NotionManager(settings.notionApiKey)
        page_id = notion.extract_page_id(settings.notionPageUrl)
        databases = await notion.search_databases(page_id)
        
        await notion.save_character(
            databases["character_db_id"],
            settings.characterName,
            settings.mbti
        )
        
        await notion.add_user_to_admin_db(
            settings.dict(),
            databases
        )
        
        return {
            "status": "success",
            "message": "Character created successfully",
            "data": {
                "characterName": settings.characterName,
                "mbti": settings.mbti,
                "databases": databases
            }
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        print("Error:", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process request: {str(e)}")

@app.get("/quests/generate/{character_name}")
async def generate_quests_endpoint(character_name: str):
    """특정 사용자를 위한 퀘스트를 생성하고 노션 DB에 저장"""
    try:
        result = await generate_quests_for_user(character_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/daily/wrap-up/{character_name}")
async def daily_wrap_up(character_name: str, request: DailyWrapUpRequest):
    """일일 활동 요약 생성"""
    try:
        user_data = await admin_notion.get_user_data(character_name)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")

        user_notion = NotionManager(user_data["notion_api_key"])
        
        try:
            target_date = datetime.strptime(request.date, "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

        activities = await user_notion.get_daily_activities(
            user_data["database_ids"]["activity_db_id"],
            target_date
        )

        if not activities:
            return {
                "status": "success",
                "activities": [],
                "message": "No activities found for this date"
            }

        diary_page_id = await user_notion.generate_daily_timeline(
            user_data["database_ids"]["diary_db_id"],
            target_date,
            activities
        )
        
        return {
            "status": "success",
            "activities": activities,
            "notionPageUrl": f"https://notion.so/{diary_page_id.replace('-', '')}"
        }
    except Exception as e:
        print(f"Error in daily wrap-up: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    if os.environ.get("CLI_MODE"):
        asyncio.run(handle_cli_command())
    else:
        uvicorn.run(app, host="0.0.0.0", port=8000)