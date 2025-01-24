from notion_client import Client
import re
from typing import Dict, List, Optional

class NotionClient:
    def __init__(self, api_key: str):
        self.client = Client(auth=api_key)
    
    def extract_page_id(self, url: str) -> str:
        """노션 URL에서 페이지 ID를 추출합니다."""
        pattern = r"([a-f0-9]{32})"
        match = re.search(pattern, url)
        if not match:
            raise ValueError("Invalid Notion URL")
        return match.group(1)

    async def get_page_content(self, page_id: str):
        """페이지의 모든 블록을 가져옵니다."""
        return self.client.blocks.children.list(page_id)
    
    async def search_databases(self, block_id: str) -> Dict[str, str]:
        """페이지에서 시스템 데이터베이스들을 찾습니다."""
        databases = {}
        print("Searching for system databases...")
        
        try:
            blocks = await self.get_page_content(block_id)
            
            for block in blocks["results"]:
                if block["type"] == "child_database":
                    title = block["child_database"]["title"].lower()
                    print(f"Found database: {title}")
                    self._map_database(databases, title, block["id"])
                    
                    # DBIndex를 찾았다면 다른 DB도 근처에 있을 것입니다
                    if "index" in title or "dbindex" in title:
                        print("Found DBIndex, checking nearby blocks for other databases...")
                
            print(f"Found databases: {databases}")
            return databases
            
        except Exception as e:
            print(f"Error while searching databases: {str(e)}")
            raise

    def _map_database(self, databases: Dict[str, str], title: str, db_id: str):
        """데이터베이스 제목을 기반으로 매핑합니다."""
        print(f"Mapping database: {title} ({db_id})")
        # 제목에 정확히 포함된 단어로 매칭
        if "dbindex" in title:
            databases["dbindex_db_id"] = db_id
        elif "character db" in title:
            databases["character_db_id"] = db_id
        elif "activity log db" in title or "activity db" in title:
            databases["activity_db_id"] = db_id
        elif "quest db" in title:
            databases["quest_db_id"] = db_id
        elif "diary db" in title:
            databases["diary_db_id"] = db_id

    async def save_character(self, db_id: str, name: str, mbti: str):
        """캐릭터 데이터베이스에 새 캐릭터를 저장합니다."""
        return self.client.pages.create(
            parent={"database_id": db_id},
            properties={
                "Name": {"title": [{"text": {"content": name}}]},
                "MBTI": {"rich_text": [{"text": {"content": mbti}}]},
                "Goals": {"rich_text": []},
                "Preferences": {"rich_text": []}
            }
        )

    async def save_db_index(self, db_index_id: str, character_name: str, db_ids: Dict[str, str]):
        """DBIndex 데이터베이스에 데이터베이스 ID들을 저장합니다."""
        return self.client.pages.create(
            parent={"database_id": db_index_id},
            properties={
                "Config Name": {"title": [{"text": {"content": character_name}}]},
                "Character DB ID": {"rich_text": [{"text": {"content": db_ids["character_db_id"]}}]},
                "Activity DB ID": {"rich_text": [{"text": {"content": db_ids["activity_db_id"]}}]},
                "Quest DB ID": {"rich_text": [{"text": {"content": db_ids["quest_db_id"]}}]},
                "Diary DB ID": {"rich_text": [{"text": {"content": db_ids["diary_db_id"]}}]},
            }
        )