from notion_client import Client
from typing import Dict, List, Optional, Any
from datetime import datetime
import re
import os
import json
from app.agent import ReflectionAnalyzer

class NotionManager:
    def __init__(self, user_api_key: str = None):
        self.admin_api_key = os.getenv("ADMIN_NOTION_TOKEN")
        self.users_db_id = os.getenv("ADMIN_USERS_DB_ID")
        self.client = Client(auth=user_api_key) if user_api_key else None
        self.admin_client = Client(auth=self.admin_api_key) if self.admin_api_key else None
        self.reflection_analyzer = ReflectionAnalyzer()

    def extract_page_id(self, url: str) -> str:
        pattern = r"([a-f0-9]{32})"
        match = re.search(pattern, url)
        if not match:
            raise ValueError("Invalid Notion URL")
        return match.group(1)

    async def search_databases(self, block_id: str) -> Dict[str, str]:
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

    async def get_user_data(self, character_name: str) -> Optional[Dict[str, Any]]:
        try:
            response = self.admin_client.databases.query(
                database_id=self.users_db_id,
                filter={"property": "Name", "title": {"equals": character_name}}
            )
            if not response["results"]:
                return None

            user_page = response["results"][0]
            blocks = self.admin_client.blocks.children.list(user_page["id"])
            user_data = {
                "notion_api_key": None,
                "notion_url": None,
                "database_ids": {}
            }

            for block in blocks["results"]:
                if block["type"] == "paragraph" and block["paragraph"]["rich_text"]:
                    text = block["paragraph"]["rich_text"][0]["text"]["content"]
                    if "Notion API Key:" in text:
                        user_data["notion_api_key"] = text.replace("Notion API Key:", "").strip()
                    elif "Notion URL:" in text:
                        user_data["notion_url"] = text.replace("Notion URL:", "").strip()
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
            raise

    async def save_character(self, db_id: str, name: str, mbti: str, goals: str = None, preferences: str = None):
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
            print(f"Error saving character: {str(e)}")
            raise

    async def get_character_data(self, character_db_id: str) -> dict:
        """캐릭터 데이터베이스에서 사용자 정보를 가져옵니다."""
        try:
            response = self.client.databases.query(
                database_id=character_db_id,
                sorts=[{
                    "property": "Name",
                    "direction": "descending"
                }],
                page_size=1
            )

            if not response["results"]:
                print("No character data found")
                return None

            character = response["results"][0]
            
            # 속성 추출
            mbti = None
            goals = None
            preferences = None

            try:
                if character["properties"]["MBTI"]["rich_text"]:
                    mbti = character["properties"]["MBTI"]["rich_text"][0]["text"]["content"]
                
                if character["properties"].get("Goals", {}).get("rich_text"):
                    goals = character["properties"]["Goals"]["rich_text"][0]["text"]["content"]
                
                if character["properties"].get("Preferences", {}).get("rich_text"):
                    preferences = character["properties"]["Preferences"]["rich_text"][0]["text"]["content"]
            except Exception as e:
                print(f"Error extracting character properties: {str(e)}")

            print(f"Found character data - MBTI: {mbti}, Goals: {goals}, Preferences: {preferences}")
            
            return {
                "mbti": mbti,
                "goals": goals,
                "preferences": preferences
            }

        except Exception as e:
            print(f"Error getting character data: {str(e)}")
            raise

    async def generate_daily_timeline(self, diary_db_id: str, date: datetime, activities: List[dict]) -> str:
        try:
            # 시간순으로 활동 정렬
            sorted_activities = sorted(activities, key=lambda x: x["startTime"])
            
            # 타임라인 블록 생성
            content_blocks = [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"text": {"content": "🕒 하루 활동 기록"}}]
                    }
                }
            ]

            # 각 활동에 대한 블록 추가
            for activity in sorted_activities:
                content_blocks.extend([
                    {
                        "object": "block",
                        "type": "heading_3",
                        "heading_3": {
                            "rich_text": [{"text": {"content": f"{activity['startTime']} - {activity['endTime']}"}}]
                        }
                    },
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"text": {"content": activity['title']}}]
                        }
                    }
                ])
                
                if activity.get('thoughts'):
                    content_blocks.append({
                        "object": "block",
                        "type": "callout",
                        "callout": {
                            "rich_text": [{"text": {"content": activity['thoughts']}}],
                            "icon": {"emoji": "💭"}
                        }
                    })
                
                content_blocks.append({
                    "object": "block",
                    "type": "divider",
                    "divider": {}
                })

            # 타임라인 페이지 생성
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
                children=[]  # 완전히 빈 페이지
            )

            return True

        except Exception as e:
            print(f"Error generating daily timeline: {str(e)}")
            raise

    async def get_todays_journal(self, diary_db_id: str, date: datetime) -> Optional[str]:
        try:
            response = self.client.databases.query(
                database_id=diary_db_id,
                filter={
                    "and": [
                        {"property": "Date", "date": {"equals": date.strftime("%Y-%m-%d")}},
                        {"property": "Type", "select": {"equals": "Journal"}}
                    ]
                }
            )

            if not response["results"]:
                return None

            page_id = response["results"][0]["id"]
            blocks = self.client.blocks.children.list(page_id)
            
            journal_content = []
            for block in blocks["results"]:
                if block["type"] in ["paragraph", "quote"] and not block["has_children"]:
                    text = block[block["type"]].get("rich_text", [])
                    if text:
                        journal_content.append(text[0]["plain_text"])

            return "\n".join(journal_content)

        except Exception as e:
            print(f"Error getting today's journal: {str(e)}")
            raise

    async def add_user_to_admin_db(self, user_data: dict, database_ids: Dict[str, str]):
        try:
            user_page = self.admin_client.pages.create(
                parent={"database_id": self.users_db_id},
                properties={
                    "Name": {"title": [{"text": {"content": user_data["characterName"]}}]},
                    "Status": {"select": {"name": "Active"}}
                }
            )

            children = [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": f"Notion URL: {user_data['notionPageUrl']}"}}]}
                },
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": f"Notion API Key: {user_data['notionApiKey']}"}}]}
                },
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "language": "json",
                        "rich_text": [{"text": {"content": json.dumps(database_ids, ensure_ascii=False)}}]
                    }
                }
            ]

            self.admin_client.blocks.children.append(
                block_id=user_page["id"],
                children=children
            )
            return user_page["id"]
        except Exception as e:
            print(f"Error adding user to admin DB: {str(e)}")
            raise

    async def update_character(self, db_id: str, character_data: dict):
        try:
            response = self.client.databases.query(
                database_id=db_id,
                filter={"property": "Name", "title": {"equals": character_data["characterName"]}}
            )
            
            if not response["results"]:
                raise ValueError(f"Character {character_data['characterName']} not found")
                
            character_page = response["results"][0]
            
            self.client.pages.update(
                page_id=character_page["id"],
                properties={
                    "MBTI": {"rich_text": [{"text": {"content": character_data["mbti"]}}]},
                    "Goals": {"rich_text": [{"text": {"content": character_data.get("goals", "")}}]},
                    "Preferences": {"rich_text": [{"text": {"content": character_data.get("preferences", "")}}]}
                }
            )
        except Exception as e:
            print(f"Error updating character: {str(e)}")
            raise

    async def generate_reflection_questions(
        self, 
        diary_db_id: str, 
        date: datetime, 
        journal_content: str, 
        mbti: str,
        goals: str = None,
        preferences: str = None
    ) -> str:
        try:
            # AI를 사용하여 성찰 질문 생성
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