from notion_client import Client
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import os
import json
from app.agent import ReflectionAnalyzer

class NotionManager:
    def __init__(self, user_api_key: str = None, gemini_api_key: str = None):
        self.admin_api_key = os.getenv("ADMIN_NOTION_TOKEN")
        self.users_db_id = os.getenv("ADMIN_USERS_DB_ID")
        self.client = Client(auth=user_api_key) if user_api_key else None
        self.admin_client = Client(auth=self.admin_api_key) if self.admin_api_key else None
        self.reflection_analyzer = ReflectionAnalyzer(gemini_api_key) if gemini_api_key else None

    def extract_page_id(self, url: str) -> str:
        """노션 URL에서 페이지 ID를 추출합니다."""
        pattern = r"([a-f0-9]{32})"
        match = re.search(pattern, url)
        if not match:
            raise ValueError("Invalid Notion URL")
        return match.group(1)

    async def search_databases(self, block_id: str) -> Dict[str, str]:
        """페이지에서 필요한 데이터베이스들을 찾습니다."""
        databases = {}
        try:
            blocks = self.client.blocks.children.list(block_id)
            for block in blocks["results"]:
                if block["type"] == "child_database":
                    title = block["child_database"]["title"].lower()
                    if "character" in title:
                        databases["character_db_id"] = block["id"]
                    elif "diary" in title:
                        databases["diary_db_id"] = block["id"]
            return databases
        except Exception as e:
            print(f"Error searching databases: {str(e)}")
            raise

    async def update_character_info(self, db_id: str, name: str, mbti: str, goals: str = None, preferences: str = None):
        """Character DB에서 사용자 정보를 업데이트합니다."""
        try:
            # 사용자 페이지 찾기
            response = self.client.databases.query(
                database_id=db_id,
                filter={"property": "Name", "title": {"equals": name}}
            )
            
            if not response["results"]:
                raise ValueError(f"User {name} not found in Character DB")
                
            user_page = response["results"][0]
            
            # 사용자 정보 업데이트
            self.client.pages.update(
                page_id=user_page["id"],
                properties={
                    "MBTI": {"rich_text": [{"text": {"content": mbti}}]},
                    "Goals": {"rich_text": [{"text": {"content": goals or ""}}]},
                    "Preferences": {"rich_text": [{"text": {"content": preferences or ""}}]}
                }
            )
            
        except Exception as e:
            print(f"Error updating character info: {str(e)}")
            raise

    async def get_user_data(self, user_name: str) -> Optional[Dict[str, Any]]:
        """Admin DB에서 사용자 데이터를 가져옵니다."""
        try:
            response = self.admin_client.databases.query(
                database_id=self.users_db_id,
                filter={"property": "Name", "title": {"equals": user_name}}
            )
            
            if not response["results"]:
                return None

            user_page = response["results"][0]
            blocks = self.admin_client.blocks.children.list(user_page["id"])
            
            # 사용자 상태 가져오기
            status = "Inactive"
            if "Status" in user_page["properties"] and user_page["properties"]["Status"]["select"]:
                status = user_page["properties"]["Status"]["select"]["name"]
            
            user_data = {
                "notion_api_key": None,
                "notion_url": None,
                "gemini_api_key": None,
                "database_ids": {},
                "status": status  # 상태 정보 추가
            }

            for block in blocks["results"]:
                if block["type"] == "paragraph" and block["paragraph"]["rich_text"]:
                    text = block["paragraph"]["rich_text"][0]["text"]["content"]
                    
                    if text.startswith("Notion API Key:"):
                        user_data["notion_api_key"] = text.replace("Notion API Key:", "").strip()
                    elif text.startswith("Notion URL:"):
                        user_data["notion_url"] = text.replace("Notion URL:", "").strip()
                    elif text.startswith("Gemini API Key:"):
                        user_data["gemini_api_key"] = text.replace("Gemini API Key:", "").strip()
                elif block["type"] == "code" and block["code"]["language"] == "json":
                    try:
                        user_data["database_ids"] = json.loads(
                            block["code"]["rich_text"][0]["text"]["content"]
                        )
                    except json.JSONDecodeError:
                        print("Error parsing database IDs")

            return user_data
            
        except Exception as e:
            print(f"Error getting user data: {str(e)}")
            print(f"Error details: {e.__dict__}")
            raise

    async def save_user(self, db_id: str, name: str, mbti: str, goals: str = None, preferences: str = None):
        """사용자 데이터베이스에 새 사용자를 저장합니다."""
        try:
            return self.client.pages.create(
                parent={"database_id": db_id},
                properties={
                    "Name": {"title": [{"text": {"content": name}}]},
                    "MBTI": {"rich_text": [{"text": {"content": mbti}}]},
                    "Goals": {"rich_text": [{"text": {"content": goals or ""}}]},
                    "Preferences": {"rich_text": [{"text": {"content": preferences or ""}}]}
                }
            )
        except Exception as e:
            print(f"Error saving user: {str(e)}")
            raise

    async def add_user_to_admin_db(self, user_data: dict, database_ids: Dict[str, str]):
        """Admin DB에 사용자 정보를 추가합니다."""
        try:
            
            user_page = self.admin_client.pages.create(
                parent={"database_id": self.users_db_id},
                properties={
                    "Name": {"title": [{"text": {"content": user_data["characterName"]}}]},
                    "Status": {"select": {"name": "Inactive"}}  # 기본 상태를 Inactive로 변경
                }
            )

            # Create blocks
            blocks = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "text": {"content": f"Notion API Key: {user_data.get('notionApiKey', 'N/A')}"}
                        }]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "text": {"content": f"Gemini API Key: {user_data.get('geminiApiKey', 'N/A')}"}
                        }]
                    }
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "text": {"content": f"Notion URL: {user_data.get('notionPageUrl', 'N/A')}"}
                        }]
                    }
                },
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "language": "json",
                        "rich_text": [{
                            "text": {"content": json.dumps(database_ids, ensure_ascii=False)}
                        }]
                    }
                }
            ]

            # Append blocks
            response = self.admin_client.blocks.children.append(
                block_id=user_page["id"],
                children=blocks
            )
            
            
            return user_page["id"]
        except Exception as e:
            print(f"Error adding user to admin DB: {str(e)}")
            print(f"Error details: {e.__dict__}")  # 에러 상세 정보 출력
            raise

    async def update_user(self, db_id: str, user_data: dict):
        """사용자 정보를 업데이트합니다."""
        try:
            response = self.client.databases.query(
                database_id=db_id,
                filter={"property": "Name", "title": {"equals": user_data["characterName"]}}
            )
            
            if not response["results"]:
                raise ValueError(f"User {user_data['characterName']} not found")
                
            user_page = response["results"][0]
            
            self.client.pages.update(
                page_id=user_page["id"],
                properties={
                    "MBTI": {"rich_text": [{"text": {"content": user_data["mbti"]}}]},
                    "Goals": {"rich_text": [{"text": {"content": user_data.get("goals", "")}}]},
                    "Preferences": {"rich_text": [{"text": {"content": user_data.get("preferences", "")}}]}
                }
            )
        except Exception as e:
            print(f"Error updating user: {str(e)}")
            raise

    async def get_user_info(self, db_id: str) -> dict:
        """사용자 데이터베이스에서 사용자 정보를 가져옵니다."""
        try:
            response = self.client.databases.query(
                database_id=db_id,
                sorts=[{
                    "property": "Name",
                    "direction": "descending"
                }],
                page_size=1
            )

            if not response["results"]:
                print("No user info found")
                return None

            user = response["results"][0]
            
            # 속성 추출
            mbti = None
            goals = None
            preferences = None

            try:
                if user["properties"]["MBTI"]["rich_text"]:
                    mbti = user["properties"]["MBTI"]["rich_text"][0]["text"]["content"]
                
                if user["properties"].get("Goals", {}).get("rich_text"):
                    goals = user["properties"]["Goals"]["rich_text"][0]["text"]["content"]
                
                if user["properties"].get("Preferences", {}).get("rich_text"):
                    preferences = user["properties"]["Preferences"]["rich_text"][0]["text"]["content"]
            except Exception as e:
                print(f"Error extracting user properties: {str(e)}")

            print(f"Found user info - MBTI: {mbti}, Goals: {goals}, Preferences: {preferences}")
            
            return {
                "mbti": mbti,
                "goals": goals,
                "preferences": preferences
            }

        except Exception as e:
            print(f"Error getting user info: {str(e)}")
            raise

    async def generate_daily_timeline(self, diary_db_id: str, date: datetime, activities: List[dict]) -> str:
        """일일 타임라인과 일기 페이지를 생성합니다."""
        try:
            # 시간순으로 활동 정렬
            sorted_activities = sorted(activities, key=lambda x: x["startTime"])
            
            # 타임라인 블록 생성
            content_blocks = [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"text": {"content": "🕒 활동 기록"}}]
                    }
                }
            ]

            # 각 활동에 대한 블록 추가
            for activity in sorted_activities:
                # 활동 제목과 시간
                content_blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "text": {"content": f"**{activity['title']}** ({activity['startTime']} - {activity['endTime']})"},
                                "annotations": {"bold": True}
                            }
                        ]
                    }
                })
                
                # 생각이나 감정이 있는 경우 - 4칸 띄어쓰기 적용
                if activity.get('thoughts'):
                    content_blocks.append({
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": f"    {activity['thoughts']}"}}]
                        }
                    })

            # 노션 페이지 생성
            self.client.pages.create(
                parent={"database_id": diary_db_id},
                properties={
                    "Title": {"title": [{"text": {"content": date.strftime("%Y-%m-%d 타임라인")}}]},
                    "Date": {"date": {"start": date.strftime("%Y-%m-%d")}},
                    "Type": {"select": {"name": "Timeline"}}
                },
                children=content_blocks
            )

            # 빈 일기 페이지 생성
            self.client.pages.create(
                parent={"database_id": diary_db_id},
                properties={
                    "Title": {"title": [{"text": {"content": date.strftime("%Y-%m-%d 일기")}}]},
                    "Date": {"date": {"start": date.strftime("%Y-%m-%d")}},
                    "Type": {"select": {"name": "Journal"}}
                },
                children=[]
            )

            return True

        except Exception as e:
            print(f"Error generating daily timeline: {str(e)}")
            raise
    
    async def get_todays_journal(self, diary_db_id: str, date: datetime) -> Optional[dict]:
        """오늘의 타임라인과 일기 내용을 가져옵니다."""
        try:
            # 1. 타임라인 페이지 조회
            timeline_response = self.client.databases.query(
                database_id=diary_db_id,
                filter={
                    "and": [
                        {"property": "Date", "date": {"equals": date.strftime("%Y-%m-%d")}},
                        {"property": "Type", "select": {"equals": "Timeline"}}
                    ]
                }
            )

            # 2. 일기 페이지 조회
            journal_response = self.client.databases.query(
                database_id=diary_db_id,
                filter={
                    "and": [
                        {"property": "Date", "date": {"equals": date.strftime("%Y-%m-%d")}},
                        {"property": "Type", "select": {"equals": "Journal"}}
                    ]
                }
            )

            timeline_content = []
            journal_content = []

            # 타임라인 내용 가져오기
            if timeline_response["results"]:
                timeline_blocks = self.client.blocks.children.list(
                    timeline_response["results"][0]["id"]
                )
                
                current_activity = {}
                for block in timeline_blocks["results"]:
                    if block["type"] == "heading_3":  # 시간
                        if current_activity:  # 이전 활동 저장
                            timeline_content.append(current_activity)
                        current_activity = {
                            "time": block["heading_3"]["rich_text"][0]["text"]["content"]
                        }
                    elif block["type"] == "paragraph" and current_activity.get("time"):  # 활동 제목
                        current_activity["activity"] = block["paragraph"]["rich_text"][0]["text"]["content"]
                    elif block["type"] == "callout" and current_activity.get("time"):  # 생각/감정
                        current_activity["thoughts"] = block["callout"]["rich_text"][0]["text"]["content"]

                if current_activity:  # 마지막 활동 저장
                    timeline_content.append(current_activity)

            # 일기 내용 가져오기
            if journal_response["results"]:
                journal_blocks = self.client.blocks.children.list(
                    journal_response["results"][0]["id"]
                )
                
                for block in journal_blocks["results"]:
                    if block["type"] in ["paragraph", "quote"] and not block["has_children"]:
                        text = block[block["type"]].get("rich_text", [])
                        if text:
                            journal_content.append(text[0]["plain_text"])

            return {
                "timeline": timeline_content,
                "journal": "\n".join(journal_content)
            }

        except Exception as e:
            print(f"Error getting today's contents: {str(e)}")
            raise

    async def generate_reflection_questions(
    self, 
    diary_db_id: str, 
    date: datetime, 
    journal_content: str, 
    mbti: str,
    goals: str = None,
    preferences: str = None,
    questions: List[str] = None
) -> str:
        """성찰 질문을 생성하고 노션 페이지에 저장합니다."""
        try:
            # 질문이 전달되지 않은 경우 AI를 사용하여 성찰 질문 생성
            if questions is None:
                questions = await self.reflection_analyzer.generate_questions(
                    journal_content=journal_content,
                    mbti=mbti,
                    goals=goals,
                    preferences=preferences
                )
            
            # 질문 페이지 생성
            content_blocks = [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"text": {"content": "🤔 오늘의 성찰 질문"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"text": {"content": "일기를 바탕으로 생성된 질문들입니다. 천천히 생각하며 답변해보세요."}}],
                        "icon": {"emoji": "✨"}
                    }
                },
                {
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                }
            ]

            # 각 질문을 블록으로 추가
            for idx, question in enumerate(questions, 1):
                content_blocks.extend([
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"text": {"content": f"Q{idx}."}}]
                        }
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": question}}]
                        }
                    },
                    {
                        "object": "block",
                        "type": "divider",
                        "divider": {}
                    }
                ])

            # 노션 페이지 생성
            response = self.client.pages.create(
                parent={"database_id": diary_db_id},
                properties={
                    "Title": {"title": [{"text": {"content": date.strftime("%Y-%m-%d 성찰 질문")}}]},
                    "Date": {"date": {"start": date.strftime("%Y-%m-%d")}},
                    "Type": {"select": {"name": "Questions"}}
                },
                children=content_blocks
            )

            return response["id"]

        except Exception as e:
            print(f"Error generating reflection questions: {str(e)}")
            raise

    async def log_activity(self, user_name: str, action: str, status: str = "Success", details: str = None):
        """관리자 노션 페이지에 사용자 활동 로그를 기록합니다."""
        try:
            logs_db_id = os.getenv("ADMIN_LOGS_DB_ID")
            if not logs_db_id or not self.admin_client:
                print("로그 기록 실패: 로그 DB ID 또는 관리자 클라이언트가 없습니다.")
                return

            # 로그 페이지 생성
            log_page = self.admin_client.pages.create(
                parent={"database_id": logs_db_id},
                properties={
                    "Name": {"title": [{"text": {"content": f"{action} - {user_name}"}}]},
                    "User": {"rich_text": [{"text": {"content": user_name}}]},
                    "Action": {"select": {"name": action}},
                    "Date": {"date": {"start": datetime.now().isoformat()}},
                    "Status": {"select": {"name": status}}
                }
            )

            # 세부 정보가 있는 경우 페이지 내용에 추가
            if details:
                blocks = [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": "세부 정보:"}}]
                        }
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": details}}]
                        }
                    }
                ]
                
                # 에러 메시지인 경우 다르게 표시
                if status == "Error":
                    blocks.append({
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"text": {"content": details}}],
                            "icon": {"emoji": "⚠️"}
                        }
                    })
                
                self.admin_client.blocks.children.append(
                    block_id=log_page["id"],
                    children=blocks
                )

            return log_page["id"]
        except Exception as e:
            print(f"로그 기록 중 오류 발생: {str(e)}")
            return None