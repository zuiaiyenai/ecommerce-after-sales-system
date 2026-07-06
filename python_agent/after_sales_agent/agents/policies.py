from __future__ import annotations

from dataclasses import dataclass, field

from ..merchant_policy import MerchantPolicyRegistry, MerchantPolicyResolution, MerchantServicePolicy
from .emotion_agent import EmotionAgent
from .evidence_agent import EvidenceAgent
from .handoff_agent import HandoffAgent
from .intent_agent import IntentAgent
from ..models import (
    AfterSalesRequest,
    ConversationMessage,
    EvidenceCheckResult,
    EmotionAnalysisResult,
    HumanHandoffResult,
    Intent,
    IntentResult,
    Order,
    RiskAssessmentResult,
    StateTransitionResult,
)
from .risk_agent import RiskAgent
from .state_agent import StateMachineAgent


@dataclass(frozen=True)
class PolicyEngine:
    policy_registry: MerchantPolicyRegistry = field(default_factory=MerchantPolicyRegistry.from_env)
    intent_agent: IntentAgent = field(default_factory=IntentAgent)
    state_agent: StateMachineAgent = field(default_factory=StateMachineAgent)
    evidence_agent: EvidenceAgent = field(default_factory=EvidenceAgent)
    risk_agent: RiskAgent = field(default_factory=RiskAgent)
    handoff_agent: HandoffAgent = field(default_factory=HandoffAgent)
    emotion_agent: EmotionAgent = field(default_factory=EmotionAgent)

    def classify_intent(self, request: AfterSalesRequest, order: Order | None) -> IntentResult:
        return self.intent_agent.classify(request, order)

    def resolve_policy(
        self,
        request: AfterSalesRequest | None = None,
        order: Order | None = None,
    ) -> MerchantPolicyResolution:
        return self.policy_registry.resolve_with_context(order=order, request=request)

    def analyze_emotion(
        self,
        request: AfterSalesRequest,
        order: Order | None,
        *,
        service_policy: MerchantServicePolicy | None = None,
        knowledge_base: dict | None = None,
        recent_history: tuple[ConversationMessage, ...] = (),
        recent_user_messages: tuple[str, ...] = (),
    ) -> EmotionAnalysisResult:
        return self.emotion_agent.analyze(
            request,
            order,
            recent_history=recent_history,
            recent_user_messages=recent_user_messages,
            knowledge_base=knowledge_base,
            handoff_min_level=(
                service_policy.emotion_handoff_min_level
                if service_policy is not None
                else None
            ),
        )

    def evaluate_state(
        self,
        order: Order | None,
        intent: Intent,
        *,
        service_policy: MerchantServicePolicy | None = None,
    ) -> StateTransitionResult:
        return self.state_agent.evaluate(order, intent, service_policy=service_policy)

    def check_evidence(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent: Intent,
        *,
        service_policy: MerchantServicePolicy | None = None,
        knowledge_base: dict | None = None,
    ) -> EvidenceCheckResult:
        return self.evidence_agent.check(
            order,
            request,
            intent,
            service_policy=service_policy,
            knowledge_base=knowledge_base,
        )

    def assess_risk(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent: Intent,
        evidence: EvidenceCheckResult,
    ) -> RiskAssessmentResult:
        return self.risk_agent.assess(order, request, intent, evidence)

    def evaluate_handoff(
        self,
        order: Order | None,
        request: AfterSalesRequest,
        intent_result: IntentResult,
        risk_result: RiskAssessmentResult,
        evidence_result: EvidenceCheckResult,
        emotion_result: EmotionAnalysisResult,
    ) -> HumanHandoffResult:
        return self.handoff_agent.evaluate(
            order,
            request,
            intent_result,
            risk_result,
            evidence_result,
            emotion_result,
        )
