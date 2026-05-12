After writing code, please always rebuild the Docker images to ensure that the changes are reflected in the user instances. You can do this by running the following command:

docker compose -f docker-compose.user1.yml up -d --no-deps --build for Ollama and speaches

and

docker compose up -d --no-deps --build for backend and frontend.