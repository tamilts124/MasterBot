import os
import subprocess
from langchain_core.tools import tool
from .common import _truncate_output

@tool
def git_status() -> str:
    """Check the Git repository status to see modified files, staged changes, and current branch.
    Always run this before committing or pulling to understand the current state of the workspace.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        result = subprocess.run(["git", "status"], capture_output=True, text=True)
        return _truncate_output(result.stdout)
    except Exception as exc:
        return f"[Error] Git status operation failed: {exc}"

@tool
def git_stash_save(message: str = "AI Agent: Auto-stash") -> str:
    """Temporarily hide current uncommitted changes to create a clean working directory.
    Use this before pulling latest code or switching context when you have unfinished work.
    Args:
        message: A descriptive label for the stash entry.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        result = subprocess.run(["git", "stash", "save", message], capture_output=True, text=True)
        return f"Successfully stashed changes: {result.stdout}"
    except Exception as exc:
        return f"[Error] Git stash save failed: {exc}"

@tool
def git_stash_pop() -> str:
    """Restore the most recently stashed changes back into the working directory.
    Use this after a successful git pull or context switch to resume previous work.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        result = subprocess.run(["git", "stash", "pop"], capture_output=True, text=True)
        if result.returncode != 0:
            return f"[Error] Git stash pop failed (likely due to conflicts):\n{result.stdout}\n{result.stderr}"
        return f"Successfully popped stash: {result.stdout}"
    except Exception as exc:
        return f"[Error] Git stash pop failed: {exc}"

@tool
def git_pull() -> str:
    """Download and merge the latest changes from the remote repository (origin main).
    MANDATORY: Run this if `git_commit_and_push` fails due to 'non-fast-forward' errors.
    This tool ensures your local workspace is synchronized with the latest squad contributions.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository: {os.getcwd()}"

        # Attempt to pull
        result = subprocess.run(["git", "pull", "origin", "main"], capture_output=True, text=True)
        if result.returncode != 0:
            output = result.stdout + result.stderr
            if "conflict" in output.lower():
                return f"[Conflict] Merge conflicts detected. Please check `git status` to see affected files and resolve markers (<<<<, ====, >>>>) in the code.\n{output}"
            return f"[Error] Git pull failed:\n{output}"
            
        return f"Successfully pulled latest changes:\n{result.stdout}"
    except Exception as exc:
        return f"[Error] Git pull operation failed: {exc}"

@tool
def git_commit_and_push(message: str) -> str:
    """Stage all current changes, commit them with a message, and upload to the remote 'origin main'.
    Use this to share your progress with the team. 
    Args:
        message: A concise summary of the changes being pushed.
    """
    try:
        # Verify we are in a git repository
        is_repo = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, text=True)
        if is_repo.returncode != 0:
            return f"[Error] Not a git repository (or any of the parent directories): {os.getcwd()}"

        # Check for changes
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if not status.stdout.strip():
            # Still try to push in case there are local commits not yet pushed
            pass
        else:
            # Add and commit
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", message], check=True)
        
        # Push specifically to origin main
        result = subprocess.run(["git", "push", "-u", "origin", "main"], capture_output=True, text=True)
        if result.returncode != 0:
            error_msg = result.stderr
            if "non-fast-forward" in error_msg or "fetch first" in error_msg:
                return "[Error] Remote repository has changes that are not in your local branch. Your changes have already been committed locally. Please use the `git_pull` tool to sync before trying to push again."
            return f"[Error] Git push failed: {error_msg}"
            
        return f"Successfully committed and pushed: {message}"
    except Exception as exc:
        return f"[Error] Git operation failed: {exc}"
