# test
Before you can test this code, start a local mysql docker container.

```
docker run -d \
      -p 7033:3306  \
      --env MYSQL_USER=root \
      --env MYSQL_ROOT_PASSWORD=password \
      mysql:5.7
```
```
docker run -d \
      -p 6033:3306  \
      --env MYSQL_USER=root \
      --env MYSQL_ROOT_PASSWORD=password \
      mysql:5.6
```
