# models.py
"""
数据模型定义
用 Pydantic 定义 AI 必须遵守的输出格式
"""
from pydantic import BaseModel, Field


class TenderInfo(BaseModel):
    """标书核心信息"""
    项目名称: str | None = Field(None, description="招标项目的名称")
    注册资本要求: str | None = Field(None, description="对投标人注册资本的要求，如'不低于500万元'")
    必须具备的资质证书: list[str] = Field(default_factory=list, description="投标人必须持有的证书/资质列表，如['ISO 9001', '建筑工程一级']")
    投标截止时间: str | None = Field(None, description="投标截止时间")


class CompanyProfile(BaseModel):
    """公司资质信息"""
    公司注册资本: str | None = Field(None, description="公司的注册资本")
    持有的证书列表: list[str] = Field(default_factory=list, description="公司持有的证书/资质列表")


class HiddenRisks(BaseModel):
    """隐藏风险"""
    risks: list[str] = Field(default_factory=list, description="发现的隐藏风险列表")