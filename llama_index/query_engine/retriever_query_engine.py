from typing import Any, List, Optional, Sequence

from llama_index.callbacks.base import CallbackManager
from llama_index.callbacks.schema import CBEventType, EventPayload
from llama_index.indices.base_retriever import BaseRetriever
from llama_index.indices.postprocessor.types import BaseNodePostprocessor
from llama_index.indices.query.base import BaseQueryEngine
from llama_index.indices.query.schema import QueryBundle
from llama_index.indices.service_context import ServiceContext
from llama_index.response_synthesizers import (
    BaseSynthesizer,
    ResponseMode,
    get_response_synthesizer,
)
from llama_index.prompts.prompts import (
    QuestionAnswerPrompt,
    RefinePrompt,
    SimpleInputPrompt,
)
from llama_index.response.schema import RESPONSE_TYPE
from llama_index.schema import NodeWithScore


class RetrieverQueryEngine(BaseQueryEngine):
    """Retriever query engine.

    Args:
        retriever (BaseRetriever): A retriever object.
        response_synthesizer (Optional[BaseSynthesizer]): A BaseSynthesizer
            object.
        callback_manager (Optional[CallbackManager]): A callback manager.
    """

    def __init__(
        self,
        retriever: BaseRetriever,
        response_synthesizer: Optional[BaseSynthesizer] = None,
        node_postprocessors: Optional[List[BaseNodePostprocessor]] = None,
        callback_manager: Optional[CallbackManager] = None,
    ) -> None:
        self._retriever = retriever
        self._response_synthesizer = response_synthesizer or get_response_synthesizer(
            service_context=retriever.get_service_context(),
            callback_manager=callback_manager,
        )
        self._node_postprocessors = node_postprocessors or []
        super().__init__(callback_manager)

    @classmethod
    def from_args(
        cls,
        retriever: BaseRetriever,
        response_synthesizer: Optional[BaseSynthesizer] = None,
        service_context: Optional[ServiceContext] = None,
        node_postprocessors: Optional[List[BaseNodePostprocessor]] = None,
        # response synthesizer args
        response_mode: ResponseMode = ResponseMode.COMPACT,
        text_qa_template: Optional[QuestionAnswerPrompt] = None,
        refine_template: Optional[RefinePrompt] = None,
        simple_template: Optional[SimpleInputPrompt] = None,
        use_async: bool = False,
        streaming: bool = False,
        # class-specific args
        **kwargs: Any,
    ) -> "RetrieverQueryEngine":
        """Initialize a RetrieverQueryEngine object."

        Args:
            retriever (BaseRetriever): A retriever object.
            service_context (Optional[ServiceContext]): A ServiceContext object.
            node_postprocessors (Optional[List[BaseNodePostprocessor]]): A list of
                node postprocessors.
            verbose (bool): Whether to print out debug info.
            response_mode (ResponseMode): A ResponseMode object.
            text_qa_template (Optional[QuestionAnswerPrompt]): A QuestionAnswerPrompt
                object.
            refine_template (Optional[RefinePrompt]): A RefinePrompt object.
            simple_template (Optional[SimpleInputPrompt]): A SimpleInputPrompt object.

            use_async (bool): Whether to use async.
            streaming (bool): Whether to use streaming.
            optimizer (Optional[BaseTokenUsageOptimizer]): A BaseTokenUsageOptimizer
                object.

        """
        response_synthesizer = response_synthesizer or get_response_synthesizer(
            service_context=service_context,
            text_qa_template=text_qa_template,
            refine_template=refine_template,
            simple_template=simple_template,
            response_mode=response_mode,
            use_async=use_async,
            streaming=streaming,
        )

        callback_manager = (
            service_context.callback_manager if service_context else CallbackManager([])
        )

        return cls(
            retriever=retriever,
            response_synthesizer=response_synthesizer,
            callback_manager=callback_manager,
            node_postprocessors=node_postprocessors,
        )

    def _apply_node_postprocessors(
        self, nodes: List[NodeWithScore], query_bundle: QueryBundle
    ) -> List[NodeWithScore]:
        for node_postprocessor in self._node_postprocessors:
            nodes = node_postprocessor.postprocess_nodes(
                nodes, query_bundle=query_bundle
            )
        return nodes

    def retrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        nodes = self._retriever.retrieve(query_bundle)
        nodes = self._apply_node_postprocessors(nodes, query_bundle=query_bundle)

        return nodes

    async def aretrieve(self, query_bundle: QueryBundle) -> List[NodeWithScore]:
        nodes = await self._retriever.aretrieve(query_bundle)
        nodes = self._apply_node_postprocessors(nodes, query_bundle=query_bundle)

        return nodes

    def with_retriever(self, retriever: BaseRetriever) -> "RetrieverQueryEngine":
        return RetrieverQueryEngine(
            retriever=retriever,
            response_synthesizer=self._response_synthesizer,
            callback_manager=self.callback_manager,
            node_postprocessors=self._node_postprocessors,
        )

    def synthesize(
        self,
        query_bundle: QueryBundle,
        nodes: List[NodeWithScore],
        additional_source_nodes: Optional[Sequence[NodeWithScore]] = None,
    ) -> RESPONSE_TYPE:
        return self._response_synthesizer.synthesize(
            query=query_bundle,
            nodes=nodes,
            additional_source_nodes=additional_source_nodes,
        )

    async def asynthesize(
        self,
        query_bundle: QueryBundle,
        nodes: List[NodeWithScore],
        additional_source_nodes: Optional[Sequence[NodeWithScore]] = None,
    ) -> RESPONSE_TYPE:
        return await self._response_synthesizer.asynthesize(
            query=query_bundle,
            nodes=nodes,
            additional_source_nodes=additional_source_nodes,
        )

    def _query(self, query_bundle: QueryBundle) -> RESPONSE_TYPE:
        """Answer a query."""
        query_id = self.callback_manager.on_event_start(
            CBEventType.QUERY, payload={EventPayload.QUERY_STR: query_bundle.query_str}
        )

        retrieve_id = self.callback_manager.on_event_start(CBEventType.RETRIEVE)
        nodes = self.retrieve(query_bundle)
        self.callback_manager.on_event_end(
            CBEventType.RETRIEVE,
            payload={EventPayload.NODES: nodes},
            event_id=retrieve_id,
        )

        response = self._response_synthesizer.synthesize(
            query=query_bundle,
            nodes=nodes,
        )

        self.callback_manager.on_event_end(
            CBEventType.QUERY,
            payload={EventPayload.RESPONSE: response},
            event_id=query_id,
        )
        return response

    async def _aquery(self, query_bundle: QueryBundle) -> RESPONSE_TYPE:
        """Answer a query."""
        query_id = self.callback_manager.on_event_start(
            CBEventType.QUERY, payload={EventPayload.QUERY_STR: query_bundle.query_str}
        )

        retrieve_id = self.callback_manager.on_event_start(CBEventType.RETRIEVE)

        nodes = await self.aretrieve(query_bundle)

        self.callback_manager.on_event_end(
            CBEventType.RETRIEVE,
            payload={EventPayload.NODES: nodes},
            event_id=retrieve_id,
        )

        response = await self._response_synthesizer.asynthesize(
            query=query_bundle,
            nodes=nodes,
        )

        self.callback_manager.on_event_end(
            CBEventType.QUERY,
            payload={EventPayload.RESPONSE: response},
            event_id=query_id,
        )
        return response

    @property
    def retriever(self) -> BaseRetriever:
        """Get the retriever object."""
        return self._retriever
