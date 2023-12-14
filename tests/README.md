# test
Before you can test this code, start a local mysql docker container.

```
docker run -d \
      -p 8033:3306  \
      --env MYSQL_ROOT_PASSWORD=password \
      mysql:8.0
```
