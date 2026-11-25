TOP ?= ..

CXXSTD := -std=c++17
include $(TOP)/mk/common_flags.mk

BUILD = build
EXE   = bin/xcov

OPT ?= -O2
CXXFLAGS = $(COMMON_CXXFLAGS) $(OPT) -g -pthread \
           -I$(BUILD) -Isrc \
           -isystem $(TOP)/xdebug/third_party

LDFLAGS = -pthread -ldl -lcrypto -lstdc++fs

CORE_SRCS = \
	src/core/errors.cpp \
	src/core/fs.cpp \
	src/core/logging.cpp \
	src/core/sha256.cpp \
	src/core/run_manifest.cpp

API_SRCS = \
	src/api/schema.cpp \
	src/api/protocol.cpp

COVERAGE_SRCS = \
	src/coverage/ucapi_loader.cpp \
	src/coverage/ucapi_backend.cpp \
	src/coverage/coverage_ref.cpp

EXCLUSION_SRCS = \
	src/exclusion/el_parser.cpp \
	src/exclusion/csv_parser.cpp

SESSION_SRCS = \
	src/session/session.cpp

ACTION_SRCS = \
	src/actions/catalog.cpp \
	src/actions/dispatch.cpp

MAIN_SRCS = src/main.cpp

SRCS = $(CORE_SRCS) $(API_SRCS) $(COVERAGE_SRCS) $(EXCLUSION_SRCS) \
       $(SESSION_SRCS) $(ACTION_SRCS) $(MAIN_SRCS)

OBJS = $(SRCS:%.cpp=$(BUILD)/%.o)
DEPS = $(OBJS:.o=.d)

.DEFAULT_GOAL := all

all: $(EXE)

$(EXE): $(OBJS)
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -o $@ $^ $(LDFLAGS)

$(BUILD)/%.o: %.cpp
	mkdir -p $(dir $@)
	$(CXX) $(CXXFLAGS) -MMD -MP -c -o $@ $<

-include $(DEPS)

clean:
	rm -rf $(BUILD) bin

.PHONY: all clean
