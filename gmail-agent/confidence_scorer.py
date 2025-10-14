import os
import numpy as np
from typing import Dict, List, Optional
from openai import openai
from dotenv import load_dotenv

load_dotenv()


class ConfidenceScorer:
    """Calculates confidence scores for routing user requests to specialist agents.

    Uses OpenAI's text-embedding-3-small model to convert text into semantic vectors,
    then compares similarity using cosine similarity.

    Example Usage:
        scorer = ConfidenceScorer()
        scores = scorer.calculate_confidence("Send an email to my team")
        # Returns: {'gmail': 0.89, 'docs': 0.45, ...}
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the confidence scorer

        Args:
            api_key: OpenAI API key (If not provided, it will use the OPENAI_API_KEY environment variable)
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

        if not self.api_key:
            raise ValueError(
                "OpenAI API key must be provided or set in environment variable 'OPENAI_API_KEY'"
            )

        self.client = OpenAI(api_key=self.api_key)
        self.model = "text-embedding-3-small"

        # this defines the agents capabilities
        # these descriptions tells the system what to do.

        self.agent_capabilities = {
            "gmail": """
            Sends emails to recipients, read recent emails from inbox, 
            search emails using queries, reply to email threads,
            send emails with file attachments, manage email communications,
            check unread messages, handle email correspondence
            """,
            "docs": """
            Creates Google Documents, add text to documents, read document content, share documents with permissions,
            format documents professionally, collaborate on documents in real-time.
            """,
            "drive": """
                List files in Google Drive, search Drive for files,
                upload files to Drive, download files from Drive,
                organize folders, manage file permissions,
                share files with others, manage Drive storage
            """,
            "sheets": """
                Create spreadsheets, read spreadsheet data,
                write data to cells, append rows to sheets,
                analyze numerical data, manage sheet permissions,
                perform calculations, organize tabular data
            """,
        }

        print("Pre-computing agent capability embeddings...")
        self.agent_embeddings = self._precompute_embeddings()
        print("Embeddings ready! Confidence scorer initialized.\n")
    
    def _precompute_embeddings(self) -> Dict[str, List[float]]:
        """
        Pre-compute embeddings for agent capabilities.
        This is done once during initialization to save API calls lataer.
        Each agent's capability description is converted to a 1536-dimenstional vector.

        Returns:
            Dict mapping agent names to their embedding vectors
        """
        embeddings = {}

        for agent, capabilities in self.agent_capabilities.items():
            try:
                #Call OpenAI API to get embedding
                response = self.client.embeddings.create(
                    input-capabilities.strip(),
                    model=self.model
                )
                embeddings[agent] = response.data[0].embedding
                print (f" {agent.upper()} agent embedded ({len(response.data[0].embedding)} dimensions)")

            except Exception as e:
                print(f" Error embedding {agent} agent: {e}")
                #Use zero vecor as fallback
                embeddings[agent] = [0.0] * 1536

            return embeddings
        
        def _get_query_embedding(self, query: str) -> List[float]:
            """
            Convert a user query into an embedding vector.

            Args:
                query: User's natural language request

            Returns:
                1536-dimensional embedding vector
            """
            try:
                response = self.client.embeddings.create(
                    input=query.strip(),
                    model=self.model
                )
                return response.data[0].embedding
            
            except Exception as e:
                print(f" Error getting query embedding: {e}")
                return [0.0] * 1536
            
        def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
            """
            Calculate cosine similarity between two vectors.

            Cosine similarity measures between two vectors.

            Cosine similarity measures the angle between two vectors:
            - 1.0 = idential (0° angle)
            - 0.0 = orthogonal (90° angle)
            - -1.0 = opposite (180° angle)

            For our use case, values mean more similar meanings

            Args:
                vec1: First embedding vector
                vec2: Second embedding vector

            Returns:
                Similarity score between -1.0 and 1.0
            """

            vec1_np = np.array(vec1)
            vec2_np = np.array(vec2)

            #Calculate dot product and magnitudes
            dot_product = np.dot(vec1_np, vec2_np)
            magnitude1 = np.linalg.norm(vec1_np)
            magnitude2 = np.linalg.norm(vec2_np)

            #avoid division by zero
            if magnitude1 == 0 or magnitude2 == 0:
                return 0.0
            
            #cosine similarity formula
            similarity = dot_product / (magnitude1 * magnitude2)

            return float(similarity)
        
        def calculate_confidence(self, user_query: str) -> Dict[str, float]:
            """
            Calculate confidence scores for all agents given a user query.
            
            This is the MAIN method used by the supervisor agent.

            Args:
                user_query: User's natural langauge request

            Returns:
                Dictionary mapping agent names to confidence scores (0.0 to 1.0)

            Example:
                >>> scorer.calculate_confidence("Send an email to my manager")
                {'gmail': 0.892, 'docs': 0.456, 'drive': 0.389, 'sheets': 0.342}    
            """

            query_embedding = self._get_query_embedding(user_query)
            confidence_scores = {}

            #calculate similarity with each agent
            scores = {}
            for agent, agent_embedding in self.agent_embeddings.items():
                similarity = self._cosine_similarity(query_embedding, agent_embedding)
                #Round to 3 decimal places for readability
                scores[agent] = round(similarity,3)

                return scores
            
    def get_top_agents(
        self, 
        user_query: str, 
        threshold: float = 0.6, 
        max_agents: int = 3
    ) -> List[Dict[str, any]]:
        """
        Get top-scoring agents above a confidence threshold.

        This is useful for the supervisor to decide which agents to route to.

        Args:
            user_query: User's natural language request
            threshold: Minimum confidence score (default 0.6)
            max_agents: Maximum number of agents to return (default 3)

            Returns:
                List of dicts with agent info, sorted by confidence (highest first)

            Example:
                >>> scorer.get_top_agents("Create a report and email it")
                [
                    {'agent': 'gmail', 'confidence': 0.821, 'should_route': True},
                    {'agent': 'docs', 'confidence': 0.756, 'should_route': True}
                ]
        """

        #get all confidence scores

        scores = self.calculate_confidence(user_query)

        #filter by threshold and sort by score
        relevant_agents = []
        for agent, score in scores.items():
            if score >= threshold:
                relevant_agents.append({
                    'agent': agent,
                    'confidence': score,
                    'should_route': True
                })

        #sort by confidence (highest first)
        relevant_agents.sort(key=lambda x: x['confidence'], reverse=True)

        #Return top N agents
        return relevant_agents[:max_agents]
    
    def analyze_query(self, user_query: str) -> Dict:
        """
        Full analysis of a user query with routing recommendations.

        This provides eeverything the supervisor needs to make routing decisions.

        Args:
            user_query: User's natural language request

        Returns:
            Complete analysis dictionary

        Example: 
            >>> scorer.analyze_query("Send the Q4 report to my team")
            {
                'query': "Send the Q4 report to my team',
                'all_scores': {'gmail': 0.89, docs': 0.67, ...},
                'recommended_agents': [{'agent': 'gmail', 'confidence': 0.89}],
                'requires_clarification': False,
                'routing_decision': 'multi_agent'
            }
        """

        all_scores = self.calculate_confidence(user_query)

        #get recommended agents
        recommend = self.get_top_agents(user_query, threshold=0.6)

        #determine if clarification needed
        max_score = max(all_scores.values()) if all_scores else 0.0
        requires_clarification = max_score < 0.5

        #Determine routing type
        if not recommend:
            routing_decision = 'needs_clarification'
        elif len(recommend) == 1:
            routing_decision = 'single_agent'
        else:
            routing_decision = 'multi_agent'

        return{
            'query': user_query,
            'all_scores': all_scores,
            'recommended_agents': recommend,
            'requires_clarification': requires_clarification,
            'routing_decision': routing_decision,
            'max_confidence': max_score
        }
    def explain_scores(self, user_query: str) -> str:
        """
        Human-readable explanation of confidence scores/

        Useful for debugging and understanding why routing decisions were made.

        Args:
            user_query: User's natural language request

        Returns:
            Formatted string explanation of scores
        """

        analysis = self.analyze_query(user_query)

        output = []
        output.append(f"\n{'='*60}")
        output.append(f"CONFIDENCE ANALYSIS")
        output.append(f"{'='*60}")
        output.append(f"\nQuery: \"{analysis}['query'])\"")
        output.append(f"\nConfidence Scores:")

        #sort scores for display
        sorted_scores = sorted(
            analysis['all_scores'].items(),
            key=lambda x: x[1],
            reverse=True
        )

        for agent, score in sorted_scores:
            #visual bar
            bar_length = int(score * 20)
            bar = '█' * bar_length + '-' * (20 - bar_length)

            #emoji base on score

            if score >= 0.8:
                emoji = "🟢"
            elif score >= 0.6:
                emoji = "🟡"
            else:
                emoji = "🔴"

        output.append(f" {emoji} {agent:8} {score:.3f} [{bar}]")

        output.append(f"\nRouting Decision: {analysis['routing_decision'].upper().replace('_', ' ')}")
        if analysis['recommend_agents']:
            output.append(f"\nRecommended Agents:")
            for rec in analysis['recommended_agents']:
                output.append(f"  → {rec['agent'].upper()} (confidence: {rec['confidence']:.3f})")
            else:
                output.append(f"\nNo agents meet confidence threshold (max: {analysis['max_confidence']:.3f})")

            if analysis['requires_clarification']:
                output.append("\n Query too ambiguous - request clarification from user")

            output.append(f"\n{'='*60}\n")

            return "\n".join(output)
        
        #convenience function for supervisor agent
    def get_routing_decision(user_query: str, api_key: Optional[str] = None) -> Dict:
        """
        Quick function for supervisor agent to get routing information

        Args:
            user_query: User's natural language request
            api_key: OpenAI API key

        Returns:
            Routing analysis dictionary
        """
        scorer = ConfidenceScorer(api_key=api_key)
        return scorer.analyze_query(user_query)
    
if __name__ == "__main__":
    #quick test
    print("\n Confidence scorer = quick test\n")

    try:
        scorer = ConfidenceScorer()
        
        # Test query
        test_query = "Send an email to my team about the project"
        
        print(scorer.explain_scores(test_query))
        
        print("✅ Confidence scorer is working!\n")
        
    except Exception as e:
        print(f"❌ Error: {e}\n")
        print("Make sure OPENAI_API_KEY is set in your .env file!")