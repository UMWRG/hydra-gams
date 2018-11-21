from iiasa/gams

MAINTAINER stephen.knox@manchester.ac.uk

COPY . /app
WORKDIR /app

RUN chmod 755 install_gams.sh && ./install_gams.sh

CMD ["hydra-gams", "--help"]

ENTRYPOINT []
