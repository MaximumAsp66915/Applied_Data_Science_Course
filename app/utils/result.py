from typing import Optional, Any


class Result:
    """
    A standardized result object for method and function returns, encapsulating success status, operation name,
    error message, and any associated data. Used for consistent error handling and response formatting.
    """
    def __init__(
        self,
        success: bool,
        operation: str,
        error_message: Optional[str] = None,
        data: Optional[Any] = None
    ) -> None:
        """
        Initialize a Result object.
        Args:
            success (bool): Whether the operation was successful.
            operation (str): Name of the operation or method.
            error_message (Optional[str]): Error message if any.
            data (Optional[Any]): Associated data or payload.
        """
        self.success: bool = success
        self.operation: str = operation
        self.error_message: Optional[str] = error_message
        self.data: Optional[Any] = data
        self.sub_results: list[Result] = []

    async def add_sub_result(self, sub_result: 'Result') -> None:
        self.sub_results.append(sub_result)
        self.success = self.success and sub_result.success
        if not sub_result.success and sub_result.error_message:
            self.error_message += " - " + sub_result.error_message + " \n"

    def __repr__(self) -> str:
        """
        String representation of the Result object.
        Returns:
            str: Readable string for debugging/logging.
        """
        if self.sub_results:
            text = (
                f"Master_Result(success={self.success}, operation='{self.operation}', "
                f"error_message={self.error_message}, data={self.data},\n"
                f"sub_results: "
            )
            for sub_result in self.sub_results:
                text += f"\n {'+' if sub_result.success else '-'} Sub_{sub_result}"
            text += "\n)"
            return text
        else:
            return (
                f"Result(success={self.success}, operation='{self.operation}', "
                f"error_message={self.error_message}, data={self.data})"
            )
