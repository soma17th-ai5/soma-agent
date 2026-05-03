from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from soma_app.models.schemas import(
    ChatRequest,
    ChatResponse,
    ErrorResponse,
)
from soma_app.services import ChatService, EmbeddingService
from soma_app.services.service_factory import ServiceFactory
from soma_app.agents.orchestrator import soma_orchestrator
from soma_app.models.schemas.soma import SomaChatRequest, SomaAgentResponse

router = APIRouter()


@router.post("/chat/message", response_model=SomaAgentResponse, responses={400: {"model": ErrorResponse}})
async def chat_message(
    soma_request: SomaChatRequest,
    ) -> SomaAgentResponse:
    """
    Soma Agent와 대화 (의도 분류 및 툴 호출 포함)

    Args:
        soma_request (SomaChatRequest): 사용자 질문 및 세션 정보

    Returns:
        SomaAgentResponse: 에이전트 답변, 출처 정보 및 액션 제안
    """
    # 1. [Router] 사용자 채팅 요청 수신 (API 엔드포인트)
    
    # 2. [Router] Orchestrator로 질의(Query) 전달하여 비즈니스 로직 위임
    response = await soma_orchestrator.process_query(query=soma_request.message)
    
    # 7. [Router] 최종 생성된 에이전트 응답(SomaAgentResponse) 반환
    return response


@router.post("/chat", response_model=ChatResponse, responses={400: {"model": ErrorResponse}})
async def chat(
    chat_request: ChatRequest,
    chat_service: ChatService = Depends(ServiceFactory.get_chat_service),
    embedding_service: EmbeddingService = Depends(ServiceFactory.get_embedding_service),
    ) -> ChatResponse | StreamingResponse:
    """
    Chat with OpenAI API

    Args:
        chat_request (ChatRequest): Request body

    Returns:
        ChatResponse | StreamingResponse: Chat response
    """
    contexts = None
    if chat_request.rag:
        contexts = await embedding_service.rag(messages=chat_request.messages)

    if chat_request.stream:
        response = await chat_service.stream_chat(messages=chat_request.messages, model=chat_request.model.value, contexts=contexts)

        return StreamingResponse(
            content=response,
            media_type="text/event-stream")
    else:
        response = await chat_service.chat(messages=chat_request.messages, model=chat_request.model.value, contexts=contexts)

        return ChatResponse(data=response)
