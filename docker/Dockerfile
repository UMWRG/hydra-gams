from gams/gams:49

MAINTAINER stephen.knox@manchester.ac.uk

RUN apt-get update

RUN apt-get -y install locales
RUN sed -i -e 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && \
    locale-gen
ENV LANG en_US.UTF-8  
ENV LANGUAGE en_US:en  
ENV LC_ALL en_US.UTF-8 


RUN apt-get install -y software-properties-common vim libmysqlclient-dev
RUN add-apt-repository ppa:jonathonf/python-3.6
RUN apt-get update
RUN apt-get install -y build-essential

COPY . /app
WORKDIR /app

RUN chmod 755 install_gams.sh
RUN ./install_gams.sh

CMD ["hydra-gams", "--help"]

ENTRYPOINT []
