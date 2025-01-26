from notion_client import Client
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import re
import os
import json
from app.agent import Quest, Activity, DailyInsightGenerator

class NotionManager:
    def __init__(self, user_api_key: str = None):
        self.admin_api_key = os.getenv("ADMIN_NOTION_TOKEN")
        self.users_db_id = os.getenv("ADMIN_USERS_DB_ID")
        self.client = Client(auth=user_api_key) if user_api_key else None
        self.admin_client = Client(auth=self.admin_api_key) if self.admin_api_key else None

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
                    if "character db" in title:
                        databases["character_db_id"] = block["id"]
                    elif "activity log db" in title or "activity db" in title:
                        databases["activity_db_id"] = block["id"]
                    elif "quest db" in title:
                        databases["quest_db_id"] = block["id"]
                    elif "diary db" in title:
                        databases["diary_db_id"] = block["id"]
            return databases
        except Exception as e:
            print(f"Error searching databases: {str(e)}")
            raise

    async def get_character_data(self, character_db_id: str) -> Dict[str, str]:
        try:
            response = self.client.databases.query(
                database_id=character_db_id,
                page_size=1
            )
            character = response["results"][0]
            properties = character["properties"]
            return {
                "mbti": properties["MBTI"]["rich_text"][0]["text"]["content"] if properties["MBTI"]["rich_text"] else "",
                "goals": properties["Goals"]["rich_text"][0]["text"]["content"] if properties.get("Goals", {}).get("rich_text") else "",
                "preferences": properties["Preferences"]["rich_text"][0]["text"]["content"] if properties.get("Preferences", {}).get("rich_text") else ""
            }
        except Exception as e:
            print(f"Error getting character data: {str(e)}")
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
                            block["code"]["rich_text"][0]["text"]["content"].replace("'", '"')
                        )
                    except json.JSONDecodeError:
                        print("Error parsing database IDs")

            return user_data
        except Exception as e:
            print(f"Error getting user data: {str(e)}")
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
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"text": {"content": f"Last Quest Generated: {datetime.now().isoformat()}"}}]}
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

    async def save_character(self, db_id: str, name: str, mbti: str, goals: str = None, preferences: str = None):
        """캐릭터 데이터베이스에 새 캐릭터를 저장합니다."""
        return self.client.pages.create(
            parent={"database_id": db_id},
            properties={
                "Name": {"title": [{"text": {"content": name}}]},
                "MBTI": {"rich_text": [{"text": {"content": mbti}}]},
                "Goals": {"rich_text": [{"text": {"content": goals or ""}}]},
                "Preferences": {"rich_text": [{"text": {"content": preferences or ""}}]}
            }
        )

    async def get_active_quests(self, quest_db_id: str) -> List[Dict]:
        try:
            response = self.client.databases.query(
                database_id=quest_db_id,
                filter={"property": "Created At", "date": {"past_week": {}}},
                sorts=[{"property": "Created At", "direction": "descending"}]
            )
            quests = []
            for page in response["results"]:
                quests.append({
                    "id": page["id"],
                    "title": page["properties"]["Quest Name"]["title"][0]["text"]["content"],
                    "type": page["properties"]["Type"]["select"]["name"],
                    "description": page["properties"]["Description"]["rich_text"][0]["text"]["content"],
                    "created_at": page["properties"]["Created At"]["date"]["start"]
                })
            return quests
        except Exception as e:
            print(f"Error getting active quests: {str(e)}")
            raise

    async def save_quest(self, quest_db_id: str, quest: Quest):
        try:
            return self.client.pages.create(
                parent={"database_id": quest_db_id},
                properties={
                    "Quest Name": {"title": [{"text": {"content": quest.title}}]},
                    "Description": {"rich_text": [{"text": {"content": quest.description}}]},
                    "Type": {"select": {"name": quest.type}},
                    "Created At": {"date": {"start": datetime.now().isoformat()}}
                }
            )
        except Exception as e:
            print(f"Error saving quest: {str(e)}")
            raise

    async def save_activity_log(self, activity_db_id: str, quest_title: str, timer_details: dict, review: str):
        try:
            total_time_minutes = round(timer_details["totalTime"] / 60)
            pause_history = []
            if timer_details.get("pauseHistory"):
                for pause in timer_details["pauseHistory"]:
                    start = datetime.fromtimestamp(pause["startTime"]/1000).strftime("%H:%M:%S")
                    end = datetime.fromtimestamp(pause["endTime"]/1000).strftime("%H:%M:%S")
                    pause_history.append(f"{start} - {end}")

            return self.client.pages.create(
                parent={"database_id": activity_db_id},
                properties={
                    "Activity Name": {"title": [{"text": {"content": quest_title}}]},
                    "Start Time": {"date": {"start": datetime.fromtimestamp(timer_details["startTime"]/1000).isoformat()}},
                    "End Time": {"date": {"start": datetime.fromtimestamp(timer_details["endTime"]/1000).isoformat()}},
                    "Duration (min)": {"number": total_time_minutes},
                    "Pause History": {"rich_text": [{"text": {"content": "\n".join(pause_history) if pause_history else "없음"}}]},
                    "Review": {"rich_text": [{"text": {"content": review if review else "기록 없음"}}]}
                }
            )
        except Exception as e:
            print(f"Error saving activity log: {str(e)}")
            raise

    async def complete_quest(self, quest_db_id: str, quest_page_id: str):
        try:
            self.client.pages.update(
                page_id=quest_page_id,
                archived=True
            )
        except Exception as e:
            print(f"Error completing quest: {str(e)}")
            raise

    async def update_last_quest_generated(self, character_name: str):
        try:
            response = self.admin_client.databases.query(
                database_id=self.users_db_id,
                filter={"property": "Name", "title": {"equals": character_name}}
            )
            if not response["results"]:
                raise ValueError(f"User {character_name} not found")

            user_page = response["results"][0]
            blocks = self.admin_client.blocks.children.list(user_page["id"])
            timestamp = datetime.now().isoformat()

            updated = False
            for block in blocks["results"]:
                if block["type"] == "paragraph" and block["paragraph"]["rich_text"]:
                    if "Last Quest Generated:" in block["paragraph"]["rich_text"][0]["text"]["content"]:
                        self.admin_client.blocks.update(
                            block_id=block["id"],
                            paragraph={"rich_text": [{"text": {"content": f"Last Quest Generated: {timestamp}"}}]}
                        )
                        updated = True
                        break

            if not updated:
                self.admin_client.blocks.children.append(
                    block_id=user_page["id"],
                    children=[{
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {"rich_text": [{"text": {"content": f"Last Quest Generated: {timestamp}"}}]}
                    }]
                )
        except Exception as e:
            print(f"Error updating last quest generated time: {str(e)}")
            raise

    async def get_daily_activities(self, activity_db_id: str, date: datetime) -> List[Dict]:
        try:
            response = self.client.databases.query(
                database_id=activity_db_id,
                filter={
                    "and": [
                        {
                            "property": "Start Time",
                            "date": {"on_or_after": date.strftime("%Y-%m-%d")}
                        },
                        {
                            "property": "Start Time",
                            "date": {"before": (date + timedelta(days=1)).strftime("%Y-%m-%d")}
                        }
                    ]
                },
                sorts=[{"property": "Start Time", "direction": "ascending"}]
            )

            activities = []
            for page in response["results"]:
                props = page["properties"]
                activities.append({
                    "name": props["Activity Name"]["title"][0]["text"]["content"],
                    "start": datetime.fromisoformat(props["Start Time"]["date"]["start"]).strftime("%H:%M"),
                    "end": datetime.fromisoformat(props["End Time"]["date"]["start"]).strftime("%H:%M"),
                    "duration": props["Duration (min)"]["number"],
                    "review": props["Review"]["rich_text"][0]["text"]["content"] if props["Review"]["rich_text"] else ""
                })

            return activities
        except Exception as e:
            print(f"Error getting daily activities: {str(e)}")
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

    async def generate_daily_timeline(self, diary_db_id: str, target_date: datetime, activities: List[Dict]) -> str:
        try:
            activities_list = [Activity(**activity) for activity in activities]
            insight_generator = DailyInsightGenerator()
            insights = await insight_generator.analyze_daily_activities(activities_list)
            total_duration = sum(activity["duration"] for activity in activities)

            content_blocks = [
                {
                    "object": "block",
                    "type": "heading_1",
                    "heading_1": {
                        "rich_text": [{"text": {"content": f"{target_date.strftime('%Y년 %m월 %d일')} 활동 기록"}}]
                    }
                },
                {
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"text": {"content": f"총 활동시간: {total_duration}분\n{insights['summary']}"}}],
                        "icon": {"emoji": "📊"}
                    }
                },
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": "활동 패턴"}}]
                    }
                }
            ]

            for pattern in insights["patterns"]:
                content_blocks.append({
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [{"text": {"content": pattern}}]
                    }
                })

            content_blocks.extend([
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": "상세 타임라인"}}]
                    }
                }
            ])

            for activity in activities:
                content_blocks.extend([
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"text": {"content": f"• {activity['start']}-{activity['end']} "}},
                                {"text": {"content": activity['name']}, "annotations": {"bold": True}},
                                {"text": {"content": f" ({activity['duration']}분)"}}
                            ]
                        }
                    }
                ])
                if activity['review']:
                    content_blocks.append({
                        "object": "block",
                        "type": "quote",
                        "quote": {
                            "rich_text": [{"text": {"content": activity['review']}}]
                        }
                    })

            content_blocks.extend([
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": "AI 인사이트"}}]
                    }
                }
            ])

            for insight in insights["insights"]:
                content_blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"text": {"content": f"• {insight}"}}]
                    }
                })

            content_blocks.extend([
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{"text": {"content": "개선 제안"}}]
                    }
                }
            ])

            for suggestion in insights["suggestions"]:
                content_blocks.append({
                    "object": "block",
                    "type": "callout",
                    "callout": {
                        "rich_text": [{"text": {"content": suggestion}}],
                        "icon": {"emoji": "💡"}
                    }
                })

            response = self.client.pages.create(
                parent={"database_id": diary_db_id},
                properties={
                    "Date": {"title": [{"text": {"content": target_date.strftime("%Y-%m-%d")}}]},
                    "날짜": {"date": {"start": target_date.strftime("%Y-%m-%d"), "time_zone": None}},
                },
                children=content_blocks
            )

            return response["id"]

        except Exception as e:
            print(f"Error generating daily timeline: {str(e)}")
            raise

        