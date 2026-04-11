from datetime import datetime
from typing import List, Optional, Any

from sqlalchemy import select, update, delete
from sqlalchemy.dialects.sqlite import insert

from bilibrain.db.tables import skill_activations


async def activate_skill(self: Any, skill_name: str) -> None:
    """激活技能"""
    # 检查技能是否已激活
    stmt = select(skill_activations).where(
        skill_activations.c.skill_name == skill_name,
        skill_activations.c.deactivated_at.is_(None)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        existing = result.scalars().first()
    
    if existing:
        # 技能已激活，无需操作
        return
    
    # 插入或更新技能激活状态
    stmt = insert(skill_activations).values(
        skill_name=skill_name,
        activated_at=datetime.utcnow(),
        deactivated_at=None
    ).on_conflict_do_update(
        index_elements=[skill_activations.c.skill_name],
        set_={
            "activated_at": datetime.utcnow(),
            "deactivated_at": None
        }
    )
    async with self.engine.begin() as conn:
        await conn.execute(stmt)


async def deactivate_skill(self: Any, skill_name: str) -> None:
    """停用技能"""
    stmt = update(skill_activations).where(
        skill_activations.c.skill_name == skill_name,
        skill_activations.c.deactivated_at.is_(None)
    ).values(
        deactivated_at=datetime.utcnow()
    )
    async with self.engine.begin() as conn:
        result = await conn.execute(stmt)


async def get_active_skills(self: Any) -> List[str]:
    """获取所有激活的技能"""
    stmt = select(skill_activations.c.skill_name).where(
        skill_activations.c.deactivated_at.is_(None)
    )
    async with self.engine.connect() as conn:
        result = await conn.execute(stmt)
        return [row[0] for row in result.fetchall()]
