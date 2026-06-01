import time
from openai import OpenAI, APIError, APIConnectionError, RateLimitError
from app.config import config
from app.logger import logger

class LLMClient:
    def __init__(self):
        self.client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL
        )
        self.model = config.MODEL_NAME
        self.max_retries = 3
        self.retry_delay = 1
    
    def chat(self, messages, temperature=0.7):
        for attempt in range(self.max_retries):
            try:
                logger.info(f"LLM调用开始，消息长度: {len(str(messages))}")
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature
                )
                content = response.choices[0].message.content
                logger.info(f"LLM调用成功，响应长度: {len(content)}")
                return content
                
            except RateLimitError:
                logger.warning(f"Rate limit exceeded, attempt {attempt+1}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    return "API调用频率过高，请稍后再试"
                    
            except (APIError, APIConnectionError) as e:
                logger.error(f"API错误: {str(e)}")
                if attempt == self.max_retries - 1:
                    return f"服务暂时不可用: {str(e)}"
                    
            except Exception as e:
                logger.error(f"未知错误: {str(e)}")
                return f"系统错误: {str(e)}"
        
        return "服务暂时不可用"

llm_client = LLMClient()
